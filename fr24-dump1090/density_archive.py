"""Disk-staged density archives: bounded RAM, consistent snapshots, full validation.

One cell/month record is decoded at a time (maximum 1 MiB). Upload size is
bounded by available disk, not by the old 256 MiB RAM limit. No extra packages.
"""
import codecs
import json
import sqlite3
import tempfile
from contextlib import contextmanager
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from traffic_density import BASE_ZOOM, RETENTION_MONTHS, FIELDS, selected_bands, selected_count, DensityStore, month_floor, parent, polygon, public, SCHEMA, UPSERT


class JsonReader:
    def __init__(self, stream, length):
        self.stream, self.remaining = stream, length
        self.buffer = ''
        self.decoder = codecs.getincrementaldecoder('utf-8')()
        self.json = json.JSONDecoder(object_pairs_hook=self.unique)

    @staticmethod
    def unique(pairs):
        result = {}
        for key, value in pairs:
            if key in result:
                raise ValueError('duplicate JSON key')
            result[key] = value
        return result

    def fill(self):
        if self.remaining <= 0:
            return False
        data = self.stream.read(min(65536, self.remaining))
        if not data:
            raise ValueError('incomplete upload')
        self.remaining -= len(data)
        self.buffer += self.decoder.decode(data, final=self.remaining == 0)
        return True

    def peek(self):
        while True:
            self.buffer = self.buffer.lstrip()
            if self.buffer:
                return self.buffer[0]
            if not self.fill():
                return ''

    def expect(self, token):
        if self.peek() != token:
            raise ValueError('invalid archive JSON structure')
        self.buffer = self.buffer[1:]

    def value(self):
        self.peek()
        while True:
            try:
                result, end = self.json.raw_decode(self.buffer)
                # A numeric token may continue into the next input chunk.
                if self.remaining and (end == len(self.buffer) or self.buffer[end] not in ' \t\r\n,:]}'):
                    if len(self.buffer) > 1024*1024:
                        raise ValueError('archive record exceeds 1 MiB')
                    self.fill()
                    continue
                if end > 1024*1024:
                    raise ValueError("archive record exceeds 1 MiB")
                self.buffer = self.buffer[end:]
                return result
            except json.JSONDecodeError as exc:
                if len(self.buffer) > 1024*1024 or not self.fill():
                    raise ValueError('invalid or oversized archive record') from exc

    def keys(self):
        self.expect('{')
        if self.peek() == '}':
            self.expect('}')
            return
        seen = set()
        while True:
            key = self.value()
            if not isinstance(key, str) or key in seen:
                raise ValueError('invalid or duplicate object key')
            seen.add(key)
            self.expect(':')
            yield key
            if self.peek() == '}':
                self.expect('}')
                return
            self.expect(',')

    def items(self):
        self.expect('[')
        if self.peek() == ']':
            self.expect(']')
            return
        while True:
            yield self.value()
            if self.peek() == ']':
                self.expect(']')
                return
            self.expect(',')


def restore_stream(store, stream, length, legacy_source=None):
    today = datetime.fromtimestamp(store.clock(), timezone.utc).date()
    with tempfile.TemporaryDirectory(prefix='.restore-', dir=store.directory) as folder:
        db = sqlite3.connect(str(Path(folder)/'staging.sqlite'))
        try:
            db.execute('CREATE TABLE records(month TEXT,cell TEXT,payload TEXT,PRIMARY KEY(month,cell))')
            reader = JsonReader(stream, length)
            metadata, months = {}, []
            found_months = False
            for key in reader.keys():
                if key != 'months':
                    if key not in ('schema_version','scheme','base_zoom','retention_months','source_type','exported_at'):
                        raise ValueError('unknown density archive field')
                    metadata[key] = reader.value()
                    continue
                found_months = True
                for month in reader.keys():
                    if date.fromisoformat(month+'-01').strftime('%Y-%m') != month:
                        raise ValueError('invalid month')
                    months.append(month)
                    for cell in reader.items():
                        # Validate expired records too, before writing anything to live history.
                        DensityStore.validate({'schema_version':1,'scheme':'geographic-quadtree',
                                               'base_zoom':BASE_ZOOM,'months':{month:[cell]}}, today)
                        try:
                            db.execute('INSERT INTO records VALUES (?,?,?)',
                                       (month,cell['cell_id'],json.dumps(cell,separators=(',',':'),allow_nan=False)))
                        except sqlite3.IntegrityError as exc:
                            raise ValueError('duplicate monthly cell') from exc
            if reader.peek() or not found_months:
                raise ValueError('trailing data or missing months')
            DensityStore.validate({**metadata,'months':{}}, today)
            store.check_source(metadata, legacy_source)
            db.commit()
            retained = sorted(m for m in months if month_floor(today)<=m<=today.strftime('%Y-%m'))
            def records(month):
                for row in db.execute('SELECT payload FROM records WHERE month=? ORDER BY cell',(month,)):
                    yield json.loads(row[0])
            return store.restore_months(((month,records(month)) for month in retained),len(months)-len(retained))
        finally:
            db.close()


@contextmanager
def snapshots(store, month=None):
    if month is not None and date.fromisoformat(month+'-01').strftime('%Y-%m') != month:
        raise ValueError('month must be YYYY-MM')
    with tempfile.TemporaryDirectory(prefix='.export-', dir=store.directory) as folder:
        paths = []
        with store.lock:
            store.prune()
            store.flush(True)
            for path in sorted(store.directory.glob('????-??.dat')):
                if month is not None and month != path.stem:
                    continue
                target = Path(folder)/path.name
                db = sqlite3.connect(target)
                try:
                    store._db(path.stem).backup(db)
                finally:
                    db.close()
                paths.append(target)
        yield Path(folder), paths


def records_from_db(db):
    current = None
    for row in db.execute('SELECT daily.*,provenance FROM daily JOIN origins USING(cell) ORDER BY cell,day'):
        if current is None or current['cell_id'] != row['cell']:
            if current is not None:
                yield current
            current = {'cell_id':row['cell'],'days':{},'provenance':row['provenance']}
        current['days'][row['day']] = {k:bool(row[k]) if k=='history_complete' else row[k] for k in FIELDS}
    if current is not None:
        yield current


def dump(value, file):
    json.dump(value,file,separators=(',',':'),allow_nan=False)


@contextmanager
def archive_file(store, month=None):
    with snapshots(store,month) as (folder, paths):
        output = folder/'archive.json'
        with output.open('w',encoding='utf-8') as file:
            header = {'schema_version':1,'scheme':'geographic-quadtree','base_zoom':BASE_ZOOM,
                      'retention_months':RETENTION_MONTHS,'source_type':store.source_type,'exported_at':store.clock()}
            file.write(json.dumps(header,separators=(',',':'))[:-1]+',"months":{')
            for index,path in enumerate(paths):
                if index:
                    file.write(',')
                file.write(json.dumps(path.stem)+':[')
                db = sqlite3.connect(path); db.row_factory = sqlite3.Row
                try:
                    for i,cell in enumerate(records_from_db(db)):
                        if i:
                            file.write(',')
                        dump(cell,file)
                finally:
                    db.close()
                file.write(']')
            file.write('}}')
        yield output


@contextmanager
def window_cells(store, start=None, end=None, zoom=BASE_ZOOM, bbox=None):
    """Consistent disk-backed window aggregate shared by exports and envelopes."""
    today = datetime.fromtimestamp(store.clock(),timezone.utc).date()
    start = date.fromisoformat(start) if start else today-timedelta(days=29)
    end = date.fromisoformat(end) if end else today
    if start>end or not 0<=zoom<=BASE_ZOOM:
        raise ValueError('invalid date window or zoom')
    if bbox is not None:
        import math
        if len(bbox)!=4 or not all(math.isfinite(v) for v in bbox) or not(-180<=bbox[0]<=bbox[2]<=180 and -90<=bbox[1]<=bbox[3]<=90):
            raise ValueError('invalid bbox')
    with snapshots(store) as (folder,paths):
        aggregate = sqlite3.connect(folder/'aggregate.sqlite'); aggregate.row_factory = sqlite3.Row
        try:
            aggregate.executescript(SCHEMA)
            for path in paths:
                if not start.strftime('%Y-%m')<=path.stem<=end.strftime('%Y-%m'):
                    continue
                db = sqlite3.connect(path); db.row_factory = sqlite3.Row
                try:
                    for row in db.execute('SELECT * FROM daily WHERE day BETWEEN ? AND ?',(start.isoformat(),end.isoformat())):
                        cell = parent(row['cell'],zoom)
                        ring = polygon(cell)
                        if bbox and (ring[1][0]<bbox[0] or ring[0][0]>bbox[2] or ring[0][1]>bbox[3] or ring[2][1]<bbox[1]):
                            continue
                        aggregate.execute(UPSERT,(cell,'window',*(row[k] for k in FIELDS)))
                        if not row['history_complete']:
                            aggregate.execute('UPDATE daily SET history_complete=0,first_observed=NULL WHERE cell=?',(cell,))
                finally:
                    db.close()
                aggregate.commit()
            window={'start':start.isoformat(),'end':end.isoformat(),'day_timezone':'UTC','display_zoom':zoom}
            yield folder, aggregate, window
        finally:
            aggregate.close()


@contextmanager
def geojson_file(store, start=None, end=None, zoom=BASE_ZOOM, bbox=None, bands='all'):
    selection = selected_bands(bands)
    with window_cells(store,start,end,zoom,bbox) as (folder,aggregate,window):
        output = folder/'cells.geojson'
        with output.open('w',encoding='utf-8') as file:
            window['selected_bands'] = list(selection)
            file.write('{"type":"FeatureCollection","source_type":'+json.dumps(store.source_type)+',"window":')
            dump(window,file); file.write(',"features":[')
            first = True
            for row in aggregate.execute('SELECT * FROM daily ORDER BY cell'):
                count = selected_count(row,selection)
                if count == 0:
                    continue
                if not first:
                    file.write(',')
                first = False
                stats = dict(row); stats['history_complete'] = bool(stats['history_complete'])
                dump({'type':'Feature','geometry':{'type':'Polygon','coordinates':[polygon(row['cell'])]},
                      'properties':{'cell_id':row['cell'],**public(stats),'selected_observation_count':count}},file)
            file.write(']}')
        yield output
