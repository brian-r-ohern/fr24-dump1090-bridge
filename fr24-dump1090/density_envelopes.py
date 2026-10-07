"""On-demand altitude consistency products from observed base-cell centers.

Fixed 0.5 degree bearings. No inference enters density or authoritative coverage.
"""
import copy
import math
import threading
import time
from collections import OrderedDict
from datetime import datetime, timedelta, timezone, date
from traffic_density import BAND_FIELDS, polygon, BASE_ZOOM
from density_archive import window_cells

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

    def get(self, home, start=None, end=None):
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
        with self.lock:
            epoch = self.store.restore_epoch
            key = (start.isoformat(),end.isoformat(),home['latitude'],home['longitude'],epoch)
            cached = self.entries.get(key)
            if cached and self.clock()-cached[0]<CACHE_SECONDS:
                self.entries.move_to_end(key)
                result=copy.deepcopy(cached[1]);result['cached']=True
                return result
            products={band:{} for band in ('all','low','middle','high')}
            with window_cells(self.store,start.isoformat(),end.isoformat()) as (_,db,window):
                for row in db.execute('SELECT * FROM daily ORDER BY cell'):
                    ring=polygon(row['cell'])
                    lon=(ring[0][0]+ring[1][0])/2;lat=(ring[0][1]+ring[2][1])/2
                    distance,bearing=distance_bearing(home,lat,lon)
                    index=int((bearing+BIN_DEGREES/2)/BIN_DEGREES)%BIN_COUNT
                    for band,bins in products.items():
                        count=row['observation_count'] if band=='all' else row[BAND_FIELDS[band]]
                        if not count:
                            continue
                        sector=bins.setdefault(index,{'bearing':index*BIN_DEGREES,'observation_count':0,
                            'qualifying_cell_passage_count':0,'occupied_cell_count':0,
                            'distance_nm':-1,'furthest_cell_id':None,'furthest_cell_observation_count':0,
                            'history_complete':True})
                        sector['observation_count']+=count
                        # Storage has combined passages, not per-altitude passages.
                        sector['qualifying_cell_passage_count']+=row['passage_count']
                        sector['occupied_cell_count']+=1
                        sector['history_complete'] = sector['history_complete'] and bool(row['history_complete'])
                        if distance>sector['distance_nm']:
                            sector.update(distance_nm=distance,furthest_cell_id=row['cell'],
                                          furthest_cell_observation_count=count,cell_center=[lon,lat])
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
            self.entries[key]=(self.clock(),copy.deepcopy(result))
            while len(self.entries)>4:
                self.entries.popitem(last=False)
            return result
