"""Disk-staged density archives: bounded RAM, consistent snapshots, full validation.

One cell/month record is decoded at a time (maximum 1 MiB). Upload size is
bounded by available disk, not by the old 256 MiB RAM limit. No extra packages.
"""
import codecs
import gzip
import shutil
import io
import json
import sqlite3
import tempfile
import time
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
    """Accept JSON or gzip; stage decompression on disk before existing validation."""
    # Limit compressed reads to Content-Length: never wait for the next HTTP request.
    prefix = stream.read(min(2, length))
    if len(prefix) != min(2, length):
        raise ValueError('incomplete upload')
    class Limited:
        def __init__(self): self.prefix, self.remaining = prefix, length-len(prefix)
        def read(self, size=-1):
            size = 65536 if size < 0 else size
            head, self.prefix = self.prefix[:size], self.prefix[size:]
            count = min(size-len(head), self.remaining)
            tail = stream.read(count) if count else b''
            if count and not tail: raise ValueError('incomplete upload')
            self.remaining -= len(tail)
            return head+tail
    limited = Limited()
    if prefix == b'\x1f\x8b':
        with tempfile.TemporaryFile(dir=store.directory) as staged:
            try:
                with gzip.GzipFile(fileobj=limited) as decoded:
                    shutil.copyfileobj(decoded, staged, length=65536)
            except (OSError, EOFError) as exc:
                raise ValueError('Invalid or incomplete gzip density archive') from exc
            size = staged.tell(); staged.seek(0)
            return _restore_json_stream(store, staged, size, legacy_source)
    return _restore_json_stream(store, limited, length, legacy_source)


def _restore_json_stream(store, stream, length, legacy_source=None):
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
def snapshots(store, month=None, diagnostic=None):
    emit = diagnostic or (lambda *args, **kwargs: None)
    snapshot_started = time.perf_counter()
    if month is not None and date.fromisoformat(month+'-01').strftime('%Y-%m') != month:
        raise ValueError('month must be YYYY-MM')
    with tempfile.TemporaryDirectory(prefix='.export-', dir=store.directory) as folder:
        paths = []
        waiting = time.perf_counter()
        emit('snapshot_lock_wait_started')
        with store.lock:
            emit('snapshot_lock_acquired', seconds=round(time.perf_counter()-waiting,4))
            stage = time.perf_counter()
            emit('flush_started')
            store.prune()
            store.flush(True)
            emit('flush_completed', seconds=round(time.perf_counter()-stage,4))
            for path in sorted(store.directory.glob('????-??.dat')):
                if month is not None and month != path.stem:
                    continue
                target = Path(folder)/path.name
                db = sqlite3.connect(target)
                try:
                    stage = time.perf_counter()
                    emit('snapshot_copy_started', month=path.stem, bytes=path.stat().st_size)
                    store._db(path.stem).backup(db)
                    emit('snapshot_copy_completed', month=path.stem, seconds=round(time.perf_counter()-stage,4))
                finally:
                    db.close()
                paths.append(target)
        emit('snapshots_ready', months=len(paths), seconds=round(time.perf_counter()-snapshot_started,4))
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
def archive_file(store, month=None, compressed=False):
    with snapshots(store,month) as (folder, paths):
        output = folder/('archive.json.gz' if compressed else 'archive.json')
        opener = gzip.open if compressed else open
        with opener(output, 'wt', encoding='utf-8') as file:
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


def aggregate_base_window(aggregate, path, start, end, emit):
    """Aggregate unchanged base cells inside SQLite; preserve exact counters."""
    stage = last_report = time.perf_counter()
    vm_steps = 0
    def progress():
        nonlocal last_report, vm_steps
        vm_steps += 100000
        now = time.perf_counter()
        if now-last_report >= 10:
            emit('window_aggregation_progress', month=path.stem,
                 strategy='sql_base_cells', vm_steps_approx=vm_steps,
                 seconds=round(now-stage,4))
            last_report = now
        return 0
    emit('window_aggregation_started', month=path.stem, strategy='sql_base_cells')
    aggregate.execute('ATTACH DATABASE ? AS envelope_source', (str(path),))
    aggregate.set_progress_handler(progress, 100000)
    try:
        # First-observed is unknown if any contributing history is incomplete
        # or has an unknown first observation. SQL MIN otherwise ignores NULL.
        expressions = ['SUM("'+field+'")' for field in FIELDS[:6]] + [
            'MIN(min_ft)', 'MAX(max_ft)',
            'CASE WHEN MIN(history_complete)=0 OR COUNT(first_observed)<COUNT(*) THEN NULL ELSE MIN(first_observed) END',
            'MAX(last_observed)', 'MIN(history_complete)']
        merge = ['"'+field+'"=daily."'+field+'"+excluded."'+field+'"' for field in FIELDS[:6]] + [
            'min_ft=CASE WHEN daily.min_ft IS NULL THEN excluded.min_ft WHEN excluded.min_ft IS NULL THEN daily.min_ft ELSE MIN(daily.min_ft,excluded.min_ft) END',
            'max_ft=CASE WHEN daily.max_ft IS NULL THEN excluded.max_ft WHEN excluded.max_ft IS NULL THEN daily.max_ft ELSE MAX(daily.max_ft,excluded.max_ft) END',
            'first_observed=CASE WHEN daily.history_complete=0 OR excluded.history_complete=0 THEN NULL ELSE MIN(daily.first_observed,excluded.first_observed) END',
            'last_observed=MAX(daily.last_observed,excluded.last_observed)',
            'history_complete=MIN(daily.history_complete,excluded.history_complete)']
        sql = ("INSERT INTO daily SELECT cell,'window',"+','.join(expressions)+
               ' FROM envelope_source.daily WHERE day BETWEEN ? AND ? GROUP BY cell '+
               'ON CONFLICT(cell,day) DO UPDATE SET '+','.join(merge))
        aggregate.execute(sql, (start.isoformat(),end.isoformat()))
        aggregate.commit()
        # Changes counts grouped cells inserted/updated, not source daily rows.
        cells = aggregate.execute('SELECT changes()').fetchone()[0]
        emit('window_aggregation_completed', month=path.stem,
             strategy='sql_base_cells', grouped_cells=cells,
             vm_steps_approx=vm_steps, seconds=round(time.perf_counter()-stage,4))
    finally:
        aggregate.set_progress_handler(None, 0)
        if aggregate.in_transaction:
            aggregate.rollback()
        aggregate.execute('DETACH DATABASE envelope_source')


@contextmanager
def window_cells(store, start=None, end=None, zoom=BASE_ZOOM, bbox=None, diagnostic=None, sql_base_cells=False):
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
    emit = diagnostic or (lambda *args, **kwargs: None)
    with snapshots(store, diagnostic=diagnostic) as (folder,paths):
        aggregate = sqlite3.connect(folder/'aggregate.sqlite'); aggregate.row_factory = sqlite3.Row
        try:
            aggregate.executescript(SCHEMA)
            for path in paths:
                if not start.strftime('%Y-%m')<=path.stem<=end.strftime('%Y-%m'):
                    continue
                if sql_base_cells and zoom == BASE_ZOOM and bbox is None:
                    aggregate_base_window(aggregate,path,start,end,emit)
                    continue
                db = sqlite3.connect(path); db.row_factory = sqlite3.Row
                stage = last_report = time.perf_counter(); rows = 0
                emit('window_aggregation_started', month=path.stem)
                try:
                    for row in db.execute('SELECT * FROM daily WHERE day BETWEEN ? AND ?',(start.isoformat(),end.isoformat())):
                        rows += 1
                        if rows % 10000 == 0 and time.perf_counter()-last_report >= 10:
                            emit('window_aggregation_progress', month=path.stem, rows=rows, seconds=round(time.perf_counter()-stage,4))
                            last_report = time.perf_counter()
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
                emit('window_aggregation_completed', month=path.stem, rows=rows, seconds=round(time.perf_counter()-stage,4))
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
