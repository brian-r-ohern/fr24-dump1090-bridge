"""Sparse geographic quadtree density, persisted in monthly SQLite chunks.

Counters are snapshots, not messages. No track interpolation ever enters this store.
Only stdlib dependencies; timestamps and day boundaries are UTC.
"""
import copy
import hashlib
import json
import math
import os
import re
import sqlite3
import threading
import time
import uuid
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

BASE_ZOOM = 17
RETENTION_MONTHS = 18
PASSAGE_GRACE_SECONDS = 90
FIELDS = ('observation_count', 'passage_count', 'below_1200_ft',
          '1200_to_17999_ft', '18000_ft_and_above', 'unknown',
          'min_ft', 'max_ft', 'first_observed', 'last_observed', 'history_complete')
SCHEMA = '''CREATE TABLE IF NOT EXISTS daily (
 cell TEXT NOT NULL, day TEXT NOT NULL,
 observation_count INTEGER NOT NULL, passage_count INTEGER NOT NULL,
 below_1200_ft INTEGER NOT NULL, "1200_to_17999_ft" INTEGER NOT NULL,
 "18000_ft_and_above" INTEGER NOT NULL, unknown INTEGER NOT NULL,
 min_ft REAL, max_ft REAL, first_observed REAL, last_observed REAL NOT NULL,
 history_complete INTEGER NOT NULL, PRIMARY KEY(cell, day));
CREATE TABLE IF NOT EXISTS origins(cell TEXT PRIMARY KEY, provenance TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS metadata(key TEXT PRIMARY KEY, value TEXT NOT NULL);
CREATE INDEX IF NOT EXISTS daily_day ON daily(day);'''

SPATIAL_SCHEMA = """CREATE TABLE IF NOT EXISTS cell_locations(cell TEXT PRIMARY KEY,x INTEGER NOT NULL,y INTEGER NOT NULL);
CREATE INDEX IF NOT EXISTS cell_locations_xy ON cell_locations(x,y);
CREATE TRIGGER IF NOT EXISTS daily_location AFTER INSERT ON daily BEGIN
 INSERT OR IGNORE INTO cell_locations VALUES (NEW.cell,
 CAST(substr(NEW.cell,4,instr(substr(NEW.cell,4),'/')-1) AS INTEGER),
 CAST(substr(NEW.cell,4+instr(substr(NEW.cell,4),'/')) AS INTEGER)); END;"""

UPSERT = '''INSERT INTO daily VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)
 ON CONFLICT(cell,day) DO UPDATE SET
 observation_count=observation_count+excluded.observation_count,
 passage_count=passage_count+excluded.passage_count,
 below_1200_ft=below_1200_ft+excluded.below_1200_ft,
 "1200_to_17999_ft"="1200_to_17999_ft"+excluded."1200_to_17999_ft",
 "18000_ft_and_above"="18000_ft_and_above"+excluded."18000_ft_and_above",
 unknown=unknown+excluded.unknown,
 min_ft=CASE WHEN min_ft IS NULL THEN excluded.min_ft WHEN excluded.min_ft IS NULL THEN min_ft ELSE min(min_ft,excluded.min_ft) END,
 max_ft=CASE WHEN max_ft IS NULL THEN excluded.max_ft WHEN excluded.max_ft IS NULL THEN max_ft ELSE max(max_ft,excluded.max_ft) END,
 first_observed=CASE WHEN history_complete=0 THEN NULL ELSE min(first_observed,excluded.first_observed) END,
 last_observed=max(last_observed,excluded.last_observed)'''


BAND_FIELDS = {'low':'below_1200_ft', 'middle':'1200_to_17999_ft', 'high':'18000_ft_and_above'}

def selected_bands(value='all'):
    if not isinstance(value,str):
        raise ValueError('bands must be all, none, or a comma-separated selection of low,middle,high')
    items = value.split(',')
    if items == ['all']:
        return ('all',)
    if items == ['none']:
        return ()
    if not items or len(items) != len(set(items)) or any(x not in BAND_FIELDS for x in items):
        raise ValueError('bands must be all, none, or a comma-separated selection of low,middle,high')
    return tuple(x for x in BAND_FIELDS if x in items)

def selected_count(stats, bands):
    return stats['observation_count'] if bands == ('all',) else sum(stats[BAND_FIELDS[b]] for b in bands)


def cell_id(lat, lon, zoom=BASE_ZOOM):
    if isinstance(lat, bool) or isinstance(lon, bool):
        raise ValueError('invalid coordinates')
    lat, lon = float(lat), float(lon)
    if not (math.isfinite(lat) and math.isfinite(lon) and -90 <= lat <= 90 and -180 <= lon <= 180):
        raise ValueError('invalid coordinates')
    n = 1 << zoom
    x = min(n - 1, int((lon + 180) / 360 * n))
    y = min(n - 1, max(0, int((90 - lat) / 180 * n)))
    return f'{zoom}/{x}/{y}'


def parse_cell(cell):
    if not isinstance(cell, str) or not re.fullmatch(r'\d+/\d+/\d+', cell):
        raise ValueError('invalid cell_id')
    z, x, y = map(int, cell.split('/'))
    if not (0 <= z <= BASE_ZOOM and 0 <= x < 1 << z and 0 <= y < 1 << z):
        raise ValueError('invalid cell_id')
    if cell != f'{z}/{x}/{y}':
        raise ValueError('noncanonical cell_id')
    return z, x, y


def parent(cell, zoom):
    z, x, y = parse_cell(cell)
    if not 0 <= zoom <= z:
        raise ValueError('invalid parent zoom')
    return f'{zoom}/{x >> (z-zoom)}/{y >> (z-zoom)}'


def polygon(cell):
    z, x, y = parse_cell(cell)
    n = 1 << z
    def point(a, b):
        return [a / n * 360 - 180, 90 - b / n * 180]
    return [point(x,y+1), point(x+1,y+1), point(x+1,y), point(x,y), point(x,y+1)]


def altitude_ft(ac):
    for key in ('alt_baro', 'alt_geom'):
        value = ac.get(key)
        if value == 'ground':
            return 0.0
        if isinstance(value, bool):
            continue
        try:
            value = float(value)
            if math.isfinite(value):
                return value
        except (ValueError, TypeError):
            pass
    return None


def month_floor(today):
    number = today.year * 12 + today.month - RETENTION_MONTHS
    return f'{number // 12:04d}-{number % 12 + 1:02d}'


def timestamp(value):
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value):
        raise ValueError('invalid timestamp')
    try:
        datetime.fromtimestamp(value, timezone.utc)
    except (ValueError, OverflowError, OSError) as exc:
        raise ValueError('invalid timestamp') from exc
    return value


def empty():
    return dict(zip(FIELDS, [0,0,0,0,0,0,None,None,None,None,True]))


def combine(target, item):
    for key in FIELDS[:6]:
        target[key] += item[key]
    for key, op in (('min_ft',min),('max_ft',max),('first_observed',min),('last_observed',max)):
        values = [x for x in (target[key],item[key]) if x is not None]
        target[key] = op(values) if values else None
    target['history_complete'] = target['history_complete'] and item['history_complete']
    if not target['history_complete']:
        target['first_observed'] = None
    return target


def public(stats):
    result = {key:stats[key] for key in ('observation_count','passage_count','first_observed','last_observed','history_complete')}
    for key in ('first_observed','last_observed'):
        if result[key] is not None:
            result[key] = datetime.fromtimestamp(result[key],timezone.utc).isoformat()
    result['altitude'] = {key:stats[key] for key in FIELDS[2:8]}
    return result


class DensityStore:
    def __init__(self, directory, clock=time.time, source_type=None):
        self.directory = Path(directory)
        self.clock = clock
        self.source_type = source_type
        self.lock = threading.RLock()
        self.connections = {}
        self.tracks = {}
        self.restore_epoch = 0
        self.last_flush = 0
        self.last_prune = None
        self.last_error = None
        self.last_query = None
        self.query_cache = {}
        self.skipped_positions = 0
        self.directory.mkdir(parents=True, exist_ok=True)
        identity = self.directory / 'identity.json'
        if identity.exists():
            stored = json.loads(identity.read_text())
            if stored.get('scheme') != 'geographic-quadtree' or stored.get('base_zoom') != BASE_ZOOM or not isinstance(stored.get('provenance'),str) or not stored['provenance']:
                raise ValueError('invalid density identity/grid metadata')
            if stored.get('source_type') != source_type:
                raise ValueError('density identity belongs to a different source')
            self.provenance = stored['provenance']
        else:
            self.provenance = str(uuid.uuid4())
            tmp = identity.with_suffix('.tmp')
            tmp.write_text(json.dumps({'provenance':self.provenance,'scheme':'geographic-quadtree','base_zoom':BASE_ZOOM,'source_type':self.source_type}))
            os.replace(tmp,identity)
        # Open retained files now: corruption blocks collection rather than overwriting history.
        self.prune()
        for path in sorted(self.directory.glob('????-??.dat')):
            self._db(path.stem)

    def _db(self, month):
        if month not in self.connections:
            path = self.directory / f'{month}.dat'
            existed = path.exists()
            db = sqlite3.connect(path,check_same_thread=False)
            db.row_factory = sqlite3.Row
            try:
                if existed:
                    meta = dict(db.execute('SELECT key,value FROM metadata'))
                    if meta != {'schema_version':'1','base_zoom':str(BASE_ZOOM)}:
                        raise ValueError(f'incompatible density chunk {month}')
                    if db.execute('PRAGMA quick_check').fetchone()[0] != 'ok':
                        raise ValueError(f'corrupt density chunk {month}')
                else:
                    db.executescript(SCHEMA)
                    db.executemany('INSERT INTO metadata VALUES (?,?)',[('schema_version','1'),('base_zoom',str(BASE_ZOOM))])
                    db.commit()
                db.executescript(SPATIAL_SCHEMA)
                # One-time index backfill for existing history; counters are untouched.
                db.execute("INSERT OR IGNORE INTO cell_locations SELECT DISTINCT cell,CAST(substr(cell,4,instr(substr(cell,4),'/')-1) AS INTEGER),CAST(substr(cell,4+instr(substr(cell,4),'/')) AS INTEGER) FROM daily WHERE cell NOT IN (SELECT cell FROM cell_locations)")
                db.commit()
                self.connections[month] = db
            except Exception:
                db.close()
                raise
        return self.connections[month]

    def prune(self):
        today = datetime.fromtimestamp(self.clock(),timezone.utc).date()
        floor = month_floor(today)
        with self.lock:
            for path in sorted(self.directory.glob('????-??.dat')):
                if path.stem < floor:
                    db = self.connections.pop(path.stem,None)
                    if db:
                        db.close()
                    path.unlink()
                    for suffix in ('-journal','-wal','-shm'):
                        Path(str(path)+suffix).unlink(missing_ok=True)
            self.last_prune = today.isoformat()

    def observe(self, aircraft, observed=None, source=None):
        source = source or self.source_type or 'unknown'
        if self.source_type is not None and source != self.source_type:
            raise ValueError('Observation source does not match density store')
        now = timestamp(self.clock() if observed is None else observed)
        day = datetime.fromtimestamp(now,timezone.utc).date().isoformat()
        with self.lock:
            if day != self.last_prune:
                self.prune()
            db = None
            seen = set()
            for ac in aircraft:
                key = str(ac.get('hex','')).strip().lower()
                if not key or key in seen:
                    continue
                seen.add(key)
                try:
                    cell = cell_id(ac['lat'],ac['lon'])
                    age = ac.get('seen_pos',ac.get('seen',0))
                    if age is not None and (isinstance(age,bool) or not math.isfinite(float(age)) or float(age) < 0 or float(age) > PASSAGE_GRACE_SECONDS):
                        raise ValueError('stale position')
                except (KeyError,ValueError,TypeError):
                    self.skipped_positions += 1
                    continue
                visits = self.tracks.setdefault((source,key),{})
                passage = int(cell not in visits or now-visits[cell] > PASSAGE_GRACE_SECONDS)
                visits[cell] = now
                altitude = altitude_ft(ac)
                band = 3 if altitude is None else (0 if altitude < 1200 else 1 if altitude < 18000 else 2)
                bands = [0,0,0,0]
                bands[band] = 1
                if db is None:
                    db = self._db(day[:7])
                db.execute(UPSERT,(cell,day,1,passage,*bands,altitude,altitude,now,now,1))
                db.execute('INSERT OR IGNORE INTO origins VALUES (?,?)',(cell,self.provenance))
            for key, visits in list(self.tracks.items()):
                for cell, last in list(visits.items()):
                    if now-last > PASSAGE_GRACE_SECONDS:
                        del visits[cell]
                if not visits:
                    del self.tracks[key]
            self.flush()

    def flush(self, force=False):
        with self.lock:
            now = self.clock()
            if force or now-self.last_flush >= 30:
                for db in self.connections.values():
                    db.commit()
                self.last_flush = now

    def close(self):
        with self.lock:
            self.flush(True)
            for db in self.connections.values():
                db.close()
            self.connections.clear()

    def clear(self):
        with self.lock:
            for db in self.connections.values():
                with db:
                    db.execute('DELETE FROM daily')
                    db.execute('DELETE FROM origins')
                    db.execute('DELETE FROM cell_locations')
                db.execute('VACUUM')
            self.tracks.clear()
            self.query_cache.clear()
            self.restore_epoch += 1
            self.last_query = None
            self.last_error = None
            self.skipped_positions = 0
        return {'cleared':'traffic_density','source_type':self.source_type}

    def _records(self, month):
        db = self._db(month)
        cells = {}
        for row in db.execute('SELECT * FROM daily ORDER BY cell,day'):
            cell = cells.setdefault(row['cell'],{'cell_id':row['cell'],'days':{}})
            cell['days'][row['day']] = {key:bool(row[key]) if key=='history_complete' else row[key] for key in FIELDS}
        origins = dict(db.execute('SELECT cell,provenance FROM origins'))
        for key,cell in cells.items():
            cell['provenance'] = origins[key]
        return list(cells.values())

    def export(self, month=None):
        if month is not None:
            try:
                if date.fromisoformat(month+'-01').strftime('%Y-%m') != month:
                    raise ValueError('invalid month')
            except (ValueError,TypeError) as exc:
                raise ValueError('month must be YYYY-MM') from exc
        with self.lock:
            self.prune()
            return {'schema_version':1,'scheme':'geographic-quadtree','base_zoom':BASE_ZOOM,
                    'retention_months':RETENTION_MONTHS,'source_type':self.source_type,'exported_at':self.clock(),
                    'months':{path.stem:self._records(path.stem) for path in sorted(self.directory.glob('????-??.dat')) if month is None or path.stem == month}}

    def query(self, start=None, end=None, zoom=BASE_ZOOM, bbox=None, bands="all", max_cells=None):
        started = time.perf_counter()
        selection = selected_bands(bands)
        if max_cells is not None and not 1 <= max_cells <= 10000:
            raise ValueError("max_cells must be 1–10000")
        requested_zoom = zoom
        today = datetime.fromtimestamp(self.clock(),timezone.utc).date()
        start = date.fromisoformat(start) if start else today-timedelta(days=29)
        end = date.fromisoformat(end) if end else today
        if start > end or not 0 <= zoom <= BASE_ZOOM:
            raise ValueError('invalid date window or zoom')
        if bbox is not None:
            if len(bbox)!=4 or not all(math.isfinite(v) for v in bbox) or not (-180<=bbox[0]<=bbox[2]<=180 and -90<=bbox[1]<=bbox[3]<=90):
                raise ValueError('bbox must be west,south,east,north without dateline wrap')
        cells = {}
        rows_read = 0
        lock_started = time.perf_counter()
        with self.lock:
            lock_wait = time.perf_counter() - lock_started
            self.prune()
            cache_key=(start.isoformat(),end.isoformat(),zoom,tuple(bbox) if bbox else None,self.restore_epoch)
            cached=self.query_cache.get(cache_key)
            cache_hit=bool(max_cells is not None and cached and time.monotonic()-cached[0]<30)
            if cache_hit:
                cells=copy.deepcopy(cached[1])
            for path in ([] if cache_hit else sorted(self.directory.glob('????-??.dat'))):
                if not start.isoformat()[:7] <= path.stem <= end.isoformat()[:7]:
                    continue
                db = self._db(path.stem)
                shift = BASE_ZOOM - zoom
                n = 1 << zoom
                if bbox:
                    # Include all children of display cells intersecting the viewport,
                    # including exact edge contact (matching the previous bbox rule).
                    xmin = max(0,math.ceil((bbox[0]+180)/360*n)-1) << shift
                    xmax = min(n-1,math.floor((bbox[2]+180)/360*n)) << shift | ((1<<shift)-1)
                    ymin = max(0,math.ceil((90-bbox[3])/180*n)-1) << shift
                    ymax = min(n-1,math.floor((90-bbox[1])/180*n)) << shift | ((1<<shift)-1)
                else:
                    xmin=ymin=0; xmax=ymax=(1<<BASE_ZOOM)-1
                for row in db.execute('''SELECT ? || "/" || ((CAST(substr(d.cell,4,instr(substr(d.cell,4),'/')-1) AS INTEGER)) >> ?) || "/" || ((CAST(substr(d.cell,4+instr(substr(d.cell,4),'/')) AS INTEGER)) >> ?) AS cell,
                    sum(observation_count) AS observation_count, sum(passage_count) AS passage_count,
                    sum(below_1200_ft) AS below_1200_ft, sum("1200_to_17999_ft") AS "1200_to_17999_ft",
                    sum("18000_ft_and_above") AS "18000_ft_and_above", sum(unknown) AS unknown,
                    min(min_ft) AS min_ft, max(max_ft) AS max_ft,
                    min(first_observed) AS first_observed, max(last_observed) AS last_observed,
                    min(history_complete) AS history_complete
                    FROM daily d JOIN cell_locations l ON l.cell=d.cell WHERE day BETWEEN ? AND ? AND l.x BETWEEN ? AND ? AND l.y BETWEEN ? AND ? GROUP BY (CAST(substr(d.cell,4,instr(substr(d.cell,4),'/')-1) AS INTEGER) >> ?), (CAST(substr(d.cell,4+instr(substr(d.cell,4),'/')) AS INTEGER) >> ?)''',(zoom,shift,shift,start.isoformat(),end.isoformat(),xmin,xmax,ymin,ymax,shift,shift)):
                    rows_read += 1
                    key = parent(row['cell'],zoom)
                    if bbox:
                        ring=polygon(key)
                        if ring[1][0]<bbox[0] or ring[0][0]>bbox[2] or ring[0][1]>bbox[3] or ring[2][1]<bbox[1]:
                            continue
                    combine(cells.setdefault(key,empty()),row)
            if max_cells is not None and not cache_hit and len(cells)<=20000:
                if len(self.query_cache)>=4:
                    self.query_cache.pop(next(iter(self.query_cache)))
                self.query_cache[cache_key]=(time.monotonic(),copy.deepcopy(cells))
        # Bound interactive geometry by merging observed children only. Never discard
        # counters or manufacture density in unobserved base cells.
        if max_cells is not None:
            cells = {k:v for k,v in cells.items() if selected_count(v,selection)>0}
            while len(cells)>max_cells and zoom>0:
                zoom -= 1
                merged = {}
                for key,value in cells.items():
                    combine(merged.setdefault(parent(key,zoom),empty()),value)
                cells = merged
        diagnostics = {'cached':cache_hit,'query_seconds':round(time.perf_counter()-started,3),
                       'lock_wait_seconds':round(lock_wait,3),'aggregated_rows_read':rows_read,
                       'returned_cells':len(cells),'requested_zoom':requested_zoom,
                       'display_zoom':zoom}
        self.last_query = diagnostics
        print('[INFO] Density query '+json.dumps(diagnostics),flush=True)
        return {'schema_version':1,'base_zoom':BASE_ZOOM,'display_zoom':zoom,
                'diagnostics':diagnostics,
                'start':start.isoformat(),'end':end.isoformat(),'day_timezone':'UTC',
                'metric':'selected_observation_count','selected_bands':list(selection),'source_type':self.source_type,
                'passage_aggregation':'sum_of_all_band_base_cell_passages',
                'cells':[{'cell_id':key,**public(value),'selected_observation_count':selected_count(value,selection)}
                         for key,value in sorted(cells.items()) if selected_count(value,selection)>0]}

    def geojson(self, **kwargs):
        payload = self.query(**kwargs)
        return {'type':'FeatureCollection','source_type':self.source_type,**({'diagnostics':payload['diagnostics']} if kwargs.get('max_cells') is not None else {}),'window':{key:payload[key] for key in ('start','end','day_timezone','display_zoom','selected_bands')},
                'features':[{'type':'Feature','geometry':{'type':'Polygon','coordinates':[polygon(cell['cell_id'])]},'properties':cell} for cell in payload['cells']]}

    def status(self):
        with self.lock:
            self.prune()
            return {'available':True,'source_type':self.source_type,'base_zoom':BASE_ZOOM,'retention_months':RETENTION_MONTHS,
                    'months':sorted(self.connections),'bytes_on_disk':sum(p.stat().st_size for p in self.directory.glob('*.dat*')),
                    'skipped_positions':self.skipped_positions,'last_error':self.last_error,'last_query':self.last_query,
                    'snapshot_interval':'selected source update cycle','passage_grace_seconds':PASSAGE_GRACE_SECONDS}

    @staticmethod
    def validate(payload, today):
        if not isinstance(payload,dict) or payload.get('schema_version') != 1 or payload.get('base_zoom') != BASE_ZOOM or payload.get('scheme') != 'geographic-quadtree':
            raise ValueError('incompatible density schema or grid')
        months=payload.get('months')
        if not isinstance(months,dict):
            raise ValueError('months must be an object')
        result={}
        for month,cells in months.items():
            try:
                date.fromisoformat(month+'-01')
            except (ValueError,TypeError) as exc:
                raise ValueError('invalid month') from exc
            if not isinstance(cells,list):
                raise ValueError('cells must be an array')
            unique=set()
            for cell in cells:
                if not isinstance(cell,dict) or parse_cell(cell.get('cell_id'))[0]!=BASE_ZOOM:
                    raise ValueError('invalid base cell')
                if cell['cell_id'] in unique:
                    raise ValueError('duplicate monthly cell')
                unique.add(cell['cell_id'])
                if not isinstance(cell.get('provenance'),str) or not 1<=len(cell['provenance'])<=256 or not isinstance(cell.get('days'),dict) or not cell['days']:
                    raise ValueError('invalid provenance or days')
                for day,stats in cell['days'].items():
                    if date.fromisoformat(day).isoformat()!=day or day[:7]!=month or not isinstance(stats,dict) or set(stats)!=set(FIELDS):
                        raise ValueError('invalid daily bucket')
                    for field in FIELDS[:6]:
                        value=stats[field]
                        if type(value)!=int or not 0<=value<=2**63-1:
                            raise ValueError('counts must be nonnegative signed 64-bit integers')
                    if stats['observation_count']!=sum(stats[key] for key in FIELDS[2:6]) or stats['passage_count']>stats['observation_count'] or stats['observation_count']==0:
                        raise ValueError('counter integrity failed')
                    if type(stats['history_complete'])!=bool:
                        raise ValueError('history_complete must be boolean')
                    first,last=stats['first_observed'],timestamp(stats['last_observed'])
                    if datetime.fromtimestamp(last,timezone.utc).date().isoformat()!=day:
                        raise ValueError('last_observed outside day')
                    if stats['history_complete']:
                        first=timestamp(first)
                        if first>last or datetime.fromtimestamp(first,timezone.utc).date().isoformat()!=day:
                            raise ValueError('first_observed outside day')
                    elif first is not None:
                        raise ValueError('incomplete history requires null first_observed')
                    low,high=stats['min_ft'],stats['max_ft']
                    if low is None or high is None:
                        if low is not None or high is not None or stats['unknown']!=stats['observation_count']:
                            raise ValueError('missing altitude bounds')
                    elif isinstance(low,bool) or isinstance(high,bool) or not isinstance(low,(int,float)) or not isinstance(high,(int,float)) or not math.isfinite(low) or not math.isfinite(high) or low>high or stats['unknown']==stats['observation_count']:
                        raise ValueError('invalid altitude bounds')
            if month_floor(today)<=month<=today.isoformat()[:7]:
                result[month]=copy.deepcopy(cells)
        return result

    @staticmethod
    def rank(cell):
        content = {'cell_id':cell['cell_id'], 'days':{day:{key:value for key,value in stats.items() if key not in ('first_observed','history_complete')} for day,stats in cell['days'].items()}}
        return (max(s['last_observed'] for s in cell['days'].values()),cell['provenance'],
                hashlib.sha256(json.dumps(content,sort_keys=True,separators=(',',':')).encode()).hexdigest())

    def restore(self,payload, legacy_source=None):
        self.check_source(payload, legacy_source)
        today=datetime.fromtimestamp(self.clock(),timezone.utc).date()
        months=self.validate(payload,today)  # Validate everything before any mutation.
        return self.restore_months(sorted(months.items()),len(payload['months'])-len(months))

    def check_source(self, payload, legacy_source=None):
        if self.source_type is None:
            return
        source = payload.get('source_type')
        if source is None:
            if legacy_source != self.source_type:
                raise ValueError('Legacy backup has no source identity; explicitly confirm it belongs to the current source.')
        elif source != self.source_type:
            raise ValueError('Backup source does not match the selected source.')

    def restore_months(self, months, ignored_months=0):
        counts={'added':0,'replaced':0,'retained':0,'ignored_months':ignored_months}
        with self.lock:
            self.query_cache.clear()
            self.prune()
            self.flush(True)
            for month,cells in months:
                db=self._db(month)
                with db:  # Atomic per monthly chunk.
                    for imported in cells:
                        key=imported['cell_id']
                        rows = db.execute('SELECT * FROM daily WHERE cell=? ORDER BY day',(key,)).fetchall()
                        current = None
                        if rows:
                            current = {'cell_id':key,'provenance':db.execute('SELECT provenance FROM origins WHERE cell=?',(key,)).fetchone()[0],
                                       'days':{r['day']:{k:bool(r[k]) if k=='history_complete' else r[k] for k in FIELDS} for r in rows}}
                        winner=copy.deepcopy(imported)
                        operation='added'
                        if current:
                            if current==imported:
                                counts['retained']+=1
                                continue
                            winner=copy.deepcopy(max((current,imported),key=self.rank))
                            operation='replaced' if self.rank(imported)>self.rank(current) else 'retained'
                            # Different origins cannot establish the beginning of their combined history.
                            if current['provenance']!=imported['provenance'] or self.rank(current)==self.rank(imported) or any(not s['history_complete'] for c in (current,imported) for s in c['days'].values()):
                                for stats in winner['days'].values():
                                    stats['first_observed']=None
                                    stats['history_complete']=False
                        db.execute('DELETE FROM daily WHERE cell=?',(key,))
                        for day,stats in sorted(winner['days'].items()):
                            db.execute('INSERT INTO daily VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)',(key,day,*(stats[k] for k in FIELDS)))
                        db.execute('INSERT OR REPLACE INTO origins VALUES (?,?)',(key,winner['provenance']))
                        counts[operation]+=1
            self.tracks.clear()
            self.restore_epoch += 1
        return counts
