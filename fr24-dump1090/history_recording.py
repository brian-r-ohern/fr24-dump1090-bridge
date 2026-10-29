"""Opt-in, source-isolated 24h normalized-input recorder for development analysis.

No raw network stream, credentials or configuration is recorded. The writer has a
bounded queue; exports stream to gzip files rather than building a day in RAM.
"""
import gzip
import json
import math
import os
from pathlib import Path
import queue
import shutil
import sqlite3
import tempfile
import threading
import time
import zlib
from collections import deque
from contextlib import contextmanager
from history_geojson import geometry
from track_history import TrackHistory

DAY=86400
SCHEMA_VERSION=1
SOURCES={'sbs_30003','aircraft_json','flights_js','swim_sfdps','swim_tfms'}

def process_memory():
    result={}
    try:
        pages=int(Path('/proc/self/statm').read_text().split()[1])
        result['process_rss_bytes']=pages*os.sysconf('SC_PAGE_SIZE')
    except (OSError,ValueError,IndexError):result['process_rss_bytes']=None
    return result

def encoded(obj):return json.dumps(obj,separators=(',',':'),allow_nan=False).encode('utf-8')
def unpack(blob):return json.loads(zlib.decompress(blob))

class HistoryRecorder:
    def __init__(self,directory,source,build_version,clock=time.time,max_bytes=2*1024**3):
        if source not in SOURCES:raise ValueError('Unsupported recording source')
        self.directory=Path(directory);self.source=source;self.version=build_version;self.clock=clock
        self.path=self.directory/(source+'.sqlite3');self.max_bytes=max_bytes
        self.lock=threading.RLock();self.control=threading.Lock();self.export_lock=threading.Lock()
        self.items=queue.Queue(maxsize=128);self.queue_bytes=0;self.queue_limit=16*1024**2
        self.enabled=False;self.ends_at=None;self.started_at=None;self.worker=None;self.closing=False
        self.stats={'snapshots_written':0,'samples_written':0,'snapshots_dropped':0,'write_errors':0,'input_bytes':0,'compressed_snapshot_bytes':0,'last_error':None}
        if self.path.exists():
            with self._database() as db:
                row=db.execute("SELECT value FROM metadata WHERE key='control'").fetchone()
                if row:
                    control=json.loads(row[0]);self.started_at=control.get('started_at');self.ends_at=control.get('ends_at')
                    self.enabled=bool(control.get('enabled')) and (self.ends_at or 0)>self.clock()
                row=db.execute("SELECT value FROM metadata WHERE key='stats'").fetchone()
                if row:self.stats.update(json.loads(row[0]))
            if self.enabled:self._ensure_worker()

    def _connect(self):
        db=sqlite3.connect(self.path,timeout=10);db.execute('PRAGMA journal_mode=WAL');db.execute('PRAGMA synchronous=NORMAL');return db

    @contextmanager
    def _database(self):
        db=self._connect()
        try:
            with db:yield db
        finally:db.close()

    def _ensure_schema(self):
        self.directory.mkdir(parents=True,exist_ok=True)
        with self._database() as db:
            db.executescript('''CREATE TABLE IF NOT EXISTS metadata(key TEXT PRIMARY KEY,value TEXT);
CREATE TABLE IF NOT EXISTS snapshots(id INTEGER PRIMARY KEY,received REAL NOT NULL,body BLOB NOT NULL,raw_bytes INTEGER NOT NULL);
CREATE INDEX IF NOT EXISTS snapshot_time ON snapshots(received);
CREATE TABLE IF NOT EXISTS samples(track_id TEXT,t REAL,received REAL,body BLOB,PRIMARY KEY(track_id,t));
CREATE INDEX IF NOT EXISTS sample_received ON samples(received);
CREATE TABLE IF NOT EXISTS track_state(track_id TEXT PRIMARY KEY,identity TEXT,sample BLOB,segment INTEGER);
CREATE TABLE IF NOT EXISTS resources(t REAL PRIMARY KEY,body TEXT);
''')

    def _save_control(self):
        with self._database() as db:
            db.execute("INSERT OR REPLACE INTO metadata VALUES ('control',?)",(json.dumps({'enabled':self.enabled,'started_at':self.started_at,'ends_at':self.ends_at}),))
            with self.lock:stats=dict(self.stats)
            db.execute("INSERT OR REPLACE INTO metadata VALUES ('stats',?)",(json.dumps(stats),))

    def _ensure_worker(self):
        if not self.worker or not self.worker.is_alive():
            self.closing=False;self.worker=threading.Thread(target=self._writer,name='history-recorder',daemon=True);self.worker.start()

    def start(self):
        with self.control:
            self._ensure_schema()
            with self.lock:
                if not self.enabled or (self.ends_at or 0)<=self.clock():
                    self.started_at=self.clock();self.ends_at=self.started_at+DAY
                self.enabled=True;self.stats['last_error']=None
            self._save_control();self._ensure_worker()
        return self.status()

    def stop(self):
        with self.control:
            with self.lock:self.enabled=False
            if self.path.exists():self._save_control()
            self.flush()
        return self.status()

    def record(self,aircraft,received,source_now=None,metadata=None,resources=None):
        with self.lock:
            if not self.enabled or self.closing:return False
            if self.clock()>=(self.ends_at or 0):self.enabled=False;return False
            try:
                raw=encoded({'schema_version':SCHEMA_VERSION,'source':self.source,'observed':received,
                    'source_now':source_now,'aircraft':aircraft,'metadata':metadata or {},'resources':resources})
            except (ValueError,TypeError) as exc:
                self.stats['snapshots_dropped']+=1;self.stats['last_error']='Serialization: '+str(exc);return False
            if self.queue_bytes+len(raw)>self.queue_limit:
                self.stats['snapshots_dropped']+=1;self.stats['last_error']='Recording queue byte limit reached';return False
            try:self.items.put_nowait(raw)
            except queue.Full:
                self.stats['snapshots_dropped']+=1;self.stats['last_error']='Recording queue full';return False
            self.queue_bytes+=len(raw)
            return True

    def flush(self,timeout=30):
        if not self.worker or not self.worker.is_alive():return
        done=threading.Event();self.items.put(done,timeout=timeout)
        if not done.wait(timeout):raise TimeoutError('Recording writer did not flush')

    def close(self):
        with self.lock:self.closing=True
        if self.worker and self.worker.is_alive():
            self.flush();self.items.put(None);self.worker.join(10)
            if self.worker.is_alive():raise TimeoutError('Recording writer did not stop')

    def _bytes(self):
        return sum(p.stat().st_size for p in (self.path,Path(str(self.path)+'-wal'),Path(str(self.path)+'-shm')) if p.exists())

    def _cutoff(self):
        # Freeze the completed recording window so a delayed download retains
        # the full test day. Starting another session advances the window.
        return min(self.clock(),self.ends_at or self.clock())-DAY

    def _prune(self,db,now):
        cutoff=self._cutoff()
        db.execute('DELETE FROM snapshots WHERE received<?',(cutoff,))
        db.execute('DELETE FROM samples WHERE received<?',(cutoff,))
        db.execute('DELETE FROM resources WHERE t<?',(cutoff,))
        db.execute('DELETE FROM track_state WHERE track_id NOT IN (SELECT DISTINCT track_id FROM samples)')

    def _writer(self):
        normalizer=TrackHistory(self.source,clock=self.clock,sample_interval=0,max_samples=1,history_seconds=DAY,return_rows=True)
        try:
            db=self._connect()
            for key,identity,body,segment in db.execute('SELECT track_id,identity,sample,segment FROM track_state'):
                normalizer.tracks[key]={'samples':deque([unpack(body)],maxlen=1),'identity':json.loads(identity),'segment':segment}
            last_prune=0;last_resources=0
            while True:
                try:item=self.items.get(timeout=1)
                except queue.Empty:
                    if self.clock()>=(self.ends_at or 0):
                        with self.lock:self.enabled=False
                    continue
                try:
                    if item is None:break
                    if isinstance(item,threading.Event):item.set();continue
                    raw=item;payload=json.loads(raw);received=payload['observed']
                    if self._bytes()>=self.max_bytes or shutil.disk_usage(self.directory).free<64*1024**2:
                        with self.lock:
                            self.enabled=False;self.stats['snapshots_dropped']+=1;self.stats['last_error']='Recording stopped: storage limit or low free space'
                        self._save_control();continue
                    write_started=time.perf_counter()
                    body=zlib.compress(raw,3)
                    accepted=normalizer.observe(payload['aircraft'],received,payload.get('source_now'),payload.get('metadata'))
                    with db:
                        db.execute('INSERT INTO snapshots(received,body,raw_bytes) VALUES (?,?,?)',(received,body,len(raw)))
                        for key,identity,row in accepted:
                            compressed=zlib.compress(encoded(row),3)
                            db.execute('INSERT OR IGNORE INTO samples VALUES (?,?,?,?)',(key,row['t'],received,compressed))
                            db.execute('INSERT OR REPLACE INTO track_state VALUES (?,?,?,?)',(key,json.dumps(identity),compressed,row['segment']))
                        if received-last_resources>=60 and payload.get('resources') is not None:
                            db.execute('INSERT OR REPLACE INTO resources VALUES (?,?)',(received,json.dumps({'observed':received,**payload['resources']})));last_resources=received
                        if received-last_prune>=300:self._prune(db,self.clock());last_prune=received
                        with self.lock:
                            self.stats['snapshots_written']+=1;self.stats['samples_written']+=len(accepted)
                            self.stats['input_bytes']+=len(raw);self.stats['compressed_snapshot_bytes']+=len(body)
                            self.stats['last_write_seconds']=round(time.perf_counter()-write_started,6)
                            stats=dict(self.stats)
                        db.execute("INSERT OR REPLACE INTO metadata VALUES ('stats',?)",(json.dumps(stats),))
                except Exception as exc:
                    db.rollback()
                    # Rebuild minimal previous-position state on the next recording session.
                    with self.lock:
                        self.enabled=False;self.stats['write_errors']+=1;self.stats['snapshots_dropped']+=1;self.stats['last_error']=type(exc).__name__+': '+str(exc)
                    try:self._save_control()
                    except Exception:pass
                finally:
                    if isinstance(item,bytes):
                        with self.lock:self.queue_bytes-=len(item)
                    self.items.task_done()
            db.close()
        except Exception as exc:
            with self.lock:
                self.enabled=False;self.stats['write_errors']+=1;self.stats['last_error']='Writer stopped: '+str(exc)
            # Wake any barriers instead of leaving an export waiting on a dead thread.
            while True:
                try:item=self.items.get_nowait()
                except queue.Empty:break
                if isinstance(item,threading.Event):item.set()
                elif isinstance(item,bytes):
                    with self.lock:self.queue_bytes-=len(item);self.stats['snapshots_dropped']+=1
                self.items.task_done()

    def status(self):
        now=self.clock()
        with self.lock:
            enabled=self.enabled and now<(self.ends_at or 0)
            result={'available':True,'source':self.source,'enabled':enabled,'started_at':self.started_at,'ends_at':self.ends_at,
                'retention_seconds':DAY,'recording_bytes':self._bytes(),'limit_bytes':self.max_bytes,
                'queue_bytes':self.queue_bytes,'queue_limit_bytes':self.queue_limit,**self.stats}
        result.update(retained_snapshots=0,retained_samples=0,oldest_received_at=None,newest_received_at=None)
        if self.path.exists():
            with self._database() as db:
                cutoff=self._cutoff()
                row=db.execute('SELECT COUNT(*),MIN(received),MAX(received) FROM snapshots WHERE received>=?',(cutoff,)).fetchone()
                result.update(retained_snapshots=row[0],oldest_received_at=row[1],newest_received_at=row[2],
                    retained_samples=db.execute('SELECT COUNT(*) FROM samples WHERE received>=?',(cutoff,)).fetchone()[0])
        return result

    def export(self,format='geojson'):
        if format not in ('geojson','jsonl'):raise ValueError('Choose geojson or jsonl')
        if not self.path.exists():raise ValueError('No recording exists for this source')
        if not self.export_lock.acquire(blocking=False):raise ValueError('Another recording export is running')
        path=None
        try:
            self.flush()
            handle=tempfile.NamedTemporaryFile(prefix='aircraft-recording-',suffix='.'+format+'.gz',delete=False);path=Path(handle.name);handle.close()
            with self._database() as db,gzip.open(path,'wt',encoding='utf-8',compresslevel=5) as out:
                db.execute('BEGIN')
                cutoff=self._cutoff()
                stats={'schema_version':SCHEMA_VERSION,'source':self.source,'build_version':self.version,'generated_at':self.clock(),
                    'history_seconds':DAY,'transient':False,'purpose':'personal retention and non-operational analysis',
                    'recording_semantics':'normalized input snapshots before history sampling; GeoJSON uses distinct valid positioned observations',
                    'recording_status':self.status(),
                    'resource_samples':[json.loads(row[0]) for row in db.execute('SELECT body FROM resources WHERE t>=? ORDER BY t',(cutoff,))]}
                if format=='jsonl':
                    out.write(json.dumps({'recording_metadata':stats})+'\n')
                    for row in db.execute('SELECT body FROM snapshots WHERE received>=? ORDER BY id',(cutoff,)):
                        out.write(zlib.decompress(row[0]).decode('utf-8')+'\n')
                else:
                    out.write('{"type":"FeatureCollection","history_geojson_version":1,"history_metadata":'+json.dumps(stats)+',"features":[')
                    first=True
                    for key,identity in db.execute('SELECT track_id,identity FROM track_state ORDER BY track_id'):
                        identity=json.loads(identity)
                        # Stream one observation at a time. Geometry is streamed separately;
                        # no aircraft/day sample list is allocated in memory.
                        bounds=db.execute('SELECT COUNT(*),MIN(t),MAX(t) FROM samples WHERE track_id=? AND received>=?',(key,cutoff)).fetchone()
                        if not bounds[0]:continue
                        if not first:out.write(',')
                        first=False
                        props={k:identity.get(k) for k in ('flight','icao_address','route_origin','route_destination')}
                        props.update(track_id=key,source=self.source,sample_count=bounds[0],start_time=bounds[1],end_time=bounds[2])
                        out.write('{"type":"Feature","id":'+json.dumps(key)+',"geometry":')
                        self._write_geometry(out,db,key,cutoff)
                        out.write(',"properties":'+json.dumps(props)[:-1]+',"record":{"identity":'+json.dumps(identity)+',"samples":[')
                        sample_first=True
                        for row in db.execute('SELECT body FROM samples WHERE track_id=? AND received>=? ORDER BY t',(key,cutoff)):
                            if not sample_first:out.write(',')
                            sample_first=False;out.write(zlib.decompress(row[0]).decode('utf-8'))
                        out.write(']}}}')
                    out.write(']}')
                db.rollback()
            return path
        except Exception:
            if path:path.unlink(missing_ok=True)
            raise
        finally:self.export_lock.release()

    @staticmethod
    def _write_geometry(out,db,key,cutoff):
        # GeometryCollection permits point-only segments without inventing lines.
        out.write('{"type":"GeometryCollection","geometries":[')
        segment=[];previous=None;first=True
        def emit(rows):
            nonlocal first
            if not first:out.write(',')
            first=False
            out.write(json.dumps({'type':'Point','coordinates':rows[0]} if len(rows)==1 else {'type':'LineString','coordinates':rows}))
        # A single uninterrupted segment can be large: use overlapping chunks of
        # 1024 points so memory stays bounded without introducing spatial gaps.
        for row in db.execute('SELECT body FROM samples WHERE track_id=? AND received>=? ORDER BY t',(key,cutoff)):
            p=unpack(row[0])
            if previous and (p.get('segment')!=previous.get('segment') or p.get('break_reason') or p['t']-previous['t']>30 or abs(p['lon']-previous['lon'])>180):
                if segment:emit(segment)
                segment=[]
            segment.append([p['lon'],p['lat']]);previous=p
            if len(segment)==1024:emit(segment);segment=segment[-1:]
        if segment:emit(segment)
        out.write(']}')
