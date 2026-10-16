"""On-demand altitude consistency products from observed base-cell centers.

Fixed 0.5 degree bearings. No inference enters density or authoritative coverage.
"""
import copy
import json
import os
import tempfile
import uuid
import math
import threading
import time
from collections import OrderedDict
from datetime import datetime, timedelta, timezone, date
from traffic_density import BAND_FIELDS, polygon, BASE_ZOOM
from density_archive import window_cells
from density_envelope_batches import reduce_batches, BATCH_SIZE

BIN_DEGREES = 0.5
BIN_COUNT = 720
CACHE_SECONDS = 300


def distance_bearing(home, lat, lon):
    p1,p2 = math.radians(home['latitude']),math.radians(lat)
    dl = math.radians(lon-home['longitude'])
    a = math.sin((p2-p1)/2)**2+math.cos(p1)*math.cos(p2)*math.sin(dl/2)**2
    distance = 3440.065*2*math.atan2(math.sqrt(min(1,a)),math.sqrt(max(0,1-a)))
    bearing = math.degrees(math.atan2(math.sin(dl)*math.cos(p2),math.cos(p1)*math.sin(p2)-math.sin(p1)*math.cos(p2)*math.cos(dl)))%360
    return distance,bearing


class EnvelopeCache:
    def __init__(self, store, clock=time.time):
        self.store, self.clock = store, clock
        self.lock = threading.Lock()
        self.entries = OrderedDict()

    def saved(self, home, status_only=False, start=None, end=None):
        """Read the last successful build without running aggregation."""
        with self.store.lock:
            path = self.store.directory/'last-envelope.json'
            try:
                with path.open() as stream:
                    saved = json.load(stream)
                if not isinstance(saved,dict):
                    raise ValueError('invalid saved envelope file')
                expected = {k:float(home[k]) for k in ('latitude','longitude')}
                if saved.get('saved_schema') != 1 or saved.get('source') != self.store.source_type or saved.get('home') != expected:
                    raise ValueError('saved envelopes do not match source or Home')
                payload = saved['payload']
                if not isinstance(payload,dict) or not isinstance(payload.get('window'),dict) or not isinstance(payload.get('products'),dict):
                    raise ValueError('invalid saved envelope payload')
                if start is not None and start != payload['window']['start'] or end is not None and end != payload['window']['end']:
                    raise ValueError('saved envelope date window does not match')
                age = max(0,self.clock()-datetime.fromisoformat(payload['generated_at']).timestamp())
                info = dict(available=True,generated_at=payload['generated_at'],age_seconds=round(age,1),
                            refresh_recommended=age>=43200,window=payload['window'])
                if status_only:
                    return info
                result = copy.deepcopy(payload)
                result.update(cached=True,saved=True,age_seconds=info['age_seconds'],refresh_recommended=info['refresh_recommended'])
                return result
            except (OSError,ValueError,TypeError,KeyError) as exc:
                if status_only:
                    return dict(available=False,reason=str(exc) if not isinstance(exc,FileNotFoundError) else 'No saved envelopes')
                raise ValueError('No matching saved envelopes; build envelopes first') from exc

    def persist(self, payload, epoch):
        # Store lock coordinates replacement with clear/import invalidation.
        with self.store.lock:
            if self.store.restore_epoch != epoch:
                raise ValueError('Density history changed during generation; build again')
            path = self.store.directory/'last-envelope.json'
            fd, temporary = tempfile.mkstemp(prefix='.envelope-',dir=self.store.directory)
            try:
                with os.fdopen(fd,'w') as stream:
                    json.dump(dict(saved_schema=1,source=self.store.source_type,home=payload['home'],payload=payload),stream,allow_nan=False)
                    stream.flush()
                    os.fsync(stream.fileno())
                os.replace(temporary,path)
            finally:
                if os.path.exists(temporary):
                    os.unlink(temporary)

    def get(self, home, start=None, end=None, force=False):
        if not home:
            raise ValueError('Home position is required for density envelopes')
        home = {k:float(home[k]) for k in ('latitude','longitude')}
        if not all(math.isfinite(v) for v in home.values()) or not(-90<=home['latitude']<=90 and -180<=home['longitude']<=180):
            raise ValueError('invalid Home position')
        today = datetime.fromtimestamp(self.store.clock(),timezone.utc).date()
        start = date.fromisoformat(start) if start else today-timedelta(days=29)
        end = date.fromisoformat(end) if end else today
        if start>end:
            raise ValueError('invalid date window')
        started = time.perf_counter()
        job_id = uuid.uuid4().hex[:12]
        def emit(stage, **values):
            if getattr(self.store, 'verbose_logging', False):
                print('[DEBUG] Envelope diagnostics '+json.dumps(dict(job_id=job_id, source=self.store.source_type, stage=stage, elapsed_seconds=round(time.perf_counter()-started,4), **values),sort_keys=True),flush=True)
        emit('request_received', start=start.isoformat(), end=end.isoformat())
        with self.lock:
            emit('generation_lock_acquired', wait_seconds=round(time.perf_counter()-started,4))
            with self.store.lock:
                self.store.prune()
                epoch = self.store.restore_epoch
            key = (start.isoformat(),end.isoformat(),home['latitude'],home['longitude'],epoch)
            cached = self.entries.get(key)
            if not force and cached and self.clock()-cached[0]<CACHE_SECONDS:
                self.entries.move_to_end(key)
                emit('cache_hit')
                result=copy.deepcopy(cached[1]);result['cached']=True
                return result
            products={band:{} for band in ('all','low','middle','high')}
            emit('cache_miss')
            with window_cells(self.store,start.isoformat(),end.isoformat(),diagnostic=emit,sql_base_cells=True) as (_,db,window):
                stage = time.perf_counter()
                emit('bearing_calculation_started', strategy='numpy_batches', batch_size=BATCH_SIZE)
                cells,batches = reduce_batches(db,home,products,distance_bearing,emit)
                emit('bearing_calculation_completed', cells=cells, batches=batches,
                     strategy='numpy_batches', seconds=round(time.perf_counter()-stage,4))
            emit('result_assembly_started')
            result={'schema_version':1,'source_type':self.store.source_type,'base_zoom':BASE_ZOOM,
                'bin_degrees':BIN_DEGREES,'total_bins':BIN_COUNT,'home':home,
                'window':{k:window[k] for k in ('start','end','day_timezone')},
                'generated_at':datetime.fromtimestamp(self.clock(),timezone.utc).isoformat(),
                'cache_seconds':CACHE_SECONDS,'cached':False,'authoritative':False,
                'position_method':'base_cell_center',
                'purpose':'altitude_band_consistency_comparison',
                'extent_kind':'reported_traffic_extent' if self.store.source_type=='swim_tfms' else 'observed_reception_extent',
                'passage_count_basis':'all-band base-cell passages in cells with selected-band observations; not altitude-specific',
                'products':{band:{'populated_bins':len(bins),'bins':[bins[i] for i in sorted(bins)]} for band,bins in products.items()}}
            self.persist(result,epoch)
            emit('saved_result_replaced')
            self.entries[key]=(self.clock(),copy.deepcopy(result))
            while len(self.entries)>4:
                self.entries.popitem(last=False)
            emit('generation_completed', cells=cells)
            return result
