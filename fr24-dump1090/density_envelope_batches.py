"""Bounded vectorized envelope reduction; scalar refinement preserves winners."""
import math
import time
import numpy as np
from traffic_density import BASE_ZOOM, BAND_FIELDS

BATCH_SIZE = 65536
BIN_COUNT = 720


def reduce_batches(db, home, products, distance_bearing, emit, batch_size=BATCH_SIZE):
    started = last_report = time.perf_counter()
    cursor = db.execute('SELECT * FROM daily ORDER BY cell')
    home_lat = math.radians(home['latitude'])
    home_lon = math.radians(home['longitude'])
    home_sin, home_cos = math.sin(home_lat), math.cos(home_lat)
    cells = batches = 0
    while True:
        rows = cursor.fetchmany(batch_size)
        if not rows:
            break
        batches += 1
        size = len(rows)
        # Stored, validated base-cell IDs; no polygons or full-history arrays.
        xy = np.asarray([tuple(map(int,row['cell'].split('/')[1:])) for row in rows], dtype=np.int64)
        n = 1 << BASE_ZOOM
        lon = ((xy[:,0]/n*360-180)+((xy[:,0]+1)/n*360-180))/2
        lat = ((90-(xy[:,1]+1)/n*180)+(90-xy[:,1]/n*180))/2
        p = np.radians(lat)
        dl = np.radians(lon)-home_lon
        a = np.sin((p-home_lat)/2)**2 + home_cos*np.cos(p)*np.sin(dl/2)**2
        a = np.clip(a,0,1)
        distances = 3440.065*2*np.arctan2(np.sqrt(a),np.sqrt(1-a))
        # Use the scalar longitude subtraction order to minimize rounding drift.
        dl = np.radians(lon-home['longitude'])
        bearings = np.degrees(np.arctan2(np.sin(dl)*np.cos(p),home_cos*np.sin(p)-home_sin*np.cos(p)*np.cos(dl)))%360
        scaled = (bearings+.25)/.5
        indices = np.floor(scaled).astype(np.int64)%BIN_COUNT
        # Exact sector decisions at floating-point boundaries use the old math.
        for i in np.flatnonzero(np.abs(scaled-np.rint(scaled))<1e-9):
            _,bearing = distance_bearing(home,float(lat[i]),float(lon[i]))
            indices[i] = int((bearing+.25)/.5)%BIN_COUNT
        passages = np.asarray([r['passage_count'] for r in rows],dtype=np.int64)
        complete = np.asarray([r['history_complete'] for r in rows],dtype=np.bool_)
        for band,bins in products.items():
            field = 'observation_count' if band=='all' else BAND_FIELDS[band]
            counts = np.asarray([r[field] for r in rows],dtype=np.int64)
            mask = counts>0
            active = indices[mask]
            totals = np.zeros(BIN_COUNT,dtype=np.int64)
            passage_totals = np.zeros(BIN_COUNT,dtype=np.int64)
            occupied = np.zeros(BIN_COUNT,dtype=np.int64)
            incomplete = np.zeros(BIN_COUNT,dtype=np.int64)
            maxima = np.full(BIN_COUNT,-1.,dtype=np.float64)
            np.add.at(totals,active,counts[mask])
            np.add.at(passage_totals,active,passages[mask])
            np.add.at(occupied,active,1)
            np.add.at(incomplete,active,~complete[mask])
            np.maximum.at(maxima,active,distances[mask])
            for index in np.flatnonzero(occupied):
                index = int(index)
                sector = bins.get(index)
                if sector is None:
                    sector = bins[index] = dict(bearing=index*.5,observation_count=0,
                        qualifying_cell_passage_count=0,occupied_cell_count=0,
                        distance_nm=-1,furthest_cell_id=None,
                        furthest_cell_observation_count=0,history_complete=True)
                sector['observation_count'] += int(totals[index])
                sector['qualifying_cell_passage_count'] += int(passage_totals[index])
                sector['occupied_cell_count'] += int(occupied[index])
                sector['history_complete'] = sector['history_complete'] and not bool(incomplete[index])
            # Refine tied/near-tied batch maxima using the original scalar math.
            # Rows retain cell order: strict > keeps the original first winner.
            candidates = np.flatnonzero(mask & (np.abs(distances-maxima[indices])<=1e-7))
            for i in candidates:
                index = int(indices[i]); sector = bins[index]
                distance,_ = distance_bearing(home,float(lat[i]),float(lon[i]))
                if distance>sector['distance_nm']:
                    sector.update(distance_nm=distance,furthest_cell_id=rows[i]['cell'],
                        furthest_cell_observation_count=int(counts[i]),
                        cell_center=[float(lon[i]),float(lat[i])])
        cells += size
        now = time.perf_counter()
        if now-last_report>=10:
            emit('bearing_calculation_progress',cells=cells,batches=batches,
                 strategy='numpy_batches',batch_size=batch_size,seconds=round(now-started,4))
            last_report=now
    return cells,batches
