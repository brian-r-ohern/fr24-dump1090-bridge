"""Bounded two-hour observed-cell tile cache for the local map view."""
import copy
import json
import math
import time
from datetime import datetime,timedelta,timezone,date
class CacheNotReady(ValueError):
    pass

TTL=7200
MAX_BYTES=32*1024*1024
MAX_ENTRIES=128
MAX_TILES=64

def view(store,start=None,end=None,zoom=17,bbox=None,bands='all',max_cells=6000,bypass_cache=False,cached_only=False):
    from traffic_density import selected_bands,selected_count,polygon,parent,combine,empty,public,timestamp,FIELDS
    began=time.perf_counter()
    selection=selected_bands(bands)
    if type(bypass_cache) is not bool or type(cached_only) is not bool:raise ValueError('cache flags must be boolean')
    if cached_only and bypass_cache:raise ValueError('cached_only cannot force a rebuild')
    if type(zoom) is not int or not 0<=zoom<=17:raise ValueError('invalid zoom')
    if type(max_cells) is not int or not 1<=max_cells<=10000:raise ValueError('max_cells must be 1–10000')
    today=datetime.fromtimestamp(store.clock(),timezone.utc).date()
    start=date.fromisoformat(start).isoformat() if start else (today-timedelta(days=29)).isoformat()
    end=date.fromisoformat(end).isoformat() if end else today.isoformat()
    if start>end:raise ValueError('invalid date window')
    def uncached(**kwargs):
        result=store.geojson(**kwargs)
        result['cache']={'generated_at':datetime.fromtimestamp(store.clock(),timezone.utc).isoformat(),'oldest_tile_age_seconds':0,'ttl_seconds':0,'hits':0,'misses':0}
        return result
    if bbox is None:
        if cached_only:raise CacheNotReady('View is not fully cached')
        return uncached(start=start,end=end,zoom=zoom,bands=bands,max_cells=max_cells,bypass_cache=bypass_cache)
    if len(bbox)!=4 or not all(math.isfinite(v) for v in bbox) or not(-180<=bbox[0]<=bbox[2]<=180 and -90<=bbox[1]<=bbox[3]<=90):raise ValueError('invalid bbox')
    tile_zoom=max(0,zoom-5);n=1<<tile_zoom
    xmin=max(0,math.ceil((bbox[0]+180)/360*n)-1);xmax=min(n-1,math.floor((bbox[2]+180)/360*n))
    ymin=max(0,math.ceil((90-bbox[3])/180*n)-1);ymax=min(n-1,math.floor((90-bbox[1])/180*n))
    if (xmax-xmin+1)*(ymax-ymin+1)>MAX_TILES:
        if cached_only:raise CacheNotReady('View is not fully cached')
        return uncached(start=start,end=end,zoom=zoom,bbox=bbox,bands=bands,max_cells=max_cells,bypass_cache=bypass_cache)
    acquired=time.perf_counter()
    with store.lock:
        if cached_only:
            inventory=cache_status(store,start=start,end=end,zoom=zoom,bbox=bbox,bands=bands)
            if inventory['to_build'] or inventory['stale']:raise CacheNotReady('View has missing or stale tiles')
        lock_wait=time.perf_counter()-acquired
        now=store.clock();cells={};hits=misses=0;generated=[];queries=[]
        for key,entry in list(store.tile_cache.items()):
            if now<entry['generated'] or now-entry['generated']>=TTL:
                store.tile_cache_bytes-=entry['bytes'];del store.tile_cache[key]
        for x in range(xmin,xmax+1):
            for y in range(ymin,ymax+1):
                owner=f'{tile_zoom}/{x}/{y}'
                key=(store.source_type,start,end,tuple(selection),zoom,tile_zoom,x,y,store.restore_epoch)
                entry=store.tile_cache.get(key)
                if entry is None or bypass_cache:
                    misses+=1
                    tile_box=[x/n*360-180,90-(y+1)/n*180,(x+1)/n*360-180,90-y/n*180]
                    store._tile_query_context=True
                    try:
                        payload=store.query(start=start,end=end,zoom=zoom,bbox=tile_box,bands=bands,bypass_cache=True)
                    finally:
                        store._tile_query_context=False
                    queries.append(payload['diagnostics'])
                    records=[c for c in payload['cells'] if parent(c['cell_id'],tile_zoom)==owner]
                    size=len(json.dumps(records,separators=(',',':')).encode('utf-8'))
                    entry={'generated':store.clock(),'records':records,'bytes':size}
                    if key in store.tile_cache:store.tile_cache_bytes-=store.tile_cache.pop(key)['bytes']
                    if size<=MAX_BYTES:
                        while store.tile_cache and (len(store.tile_cache)>=MAX_ENTRIES or store.tile_cache_bytes+size>MAX_BYTES):
                            _,removed=store.tile_cache.popitem(last=False);store.tile_cache_bytes-=removed['bytes']
                        store.tile_cache[key]=entry;store.tile_cache_bytes+=size
                else:
                    hits+=1;store.tile_cache.move_to_end(key)
                generated.append(entry['generated'])
                for cell in entry['records']:
                    ring=polygon(cell['cell_id'])
                    if ring[1][0]<bbox[0] or ring[0][0]>bbox[2] or ring[0][1]>bbox[3] or ring[2][1]<bbox[1]:continue
                    raw={**cell,**cell['altitude']}
                    raw['first_observed']=datetime.fromisoformat(cell['first_observed']).timestamp() if cell['first_observed'] is not None else None
                    raw['last_observed']=datetime.fromisoformat(cell['last_observed']).timestamp()
                    cells[cell['cell_id']]={k:raw[k] for k in FIELDS}
        display_zoom=zoom
        while len(cells)>max_cells and display_zoom>0:
            display_zoom-=1;merged={}
            for key,value in cells.items():combine(merged.setdefault(parent(key,display_zoom),empty()),value)
            cells=merged
        features=[{'type':'Feature','geometry':{'type':'Polygon','coordinates':[polygon(k)]},'properties':{'cell_id':k,**public(v),'selected_observation_count':selected_count(v,selection)}} for k,v in sorted(cells.items())]
        diagnostics={'cached':misses==0,'cache_bypassed':bypass_cache,'query_seconds':round(time.perf_counter()-began,3),'lock_wait_seconds':round(lock_wait,3),
            'aggregated_rows_read':sum(d['aggregated_rows_read'] for d in queries),'returned_cells':len(features),'requested_zoom':zoom,'display_zoom':display_zoom,
            'tile_cache_hits':hits,'tile_cache_misses':misses,'tile_zoom':tile_zoom,
            'monthly_queries':[m for d in queries for m in d['monthly_queries']]}
        generated_at=min(generated) if generated else now
        result={'type':'FeatureCollection','source_type':store.source_type,'features':features,'diagnostics':diagnostics,
            'window':{'start':start,'end':end,'day_timezone':'UTC','display_zoom':display_zoom,'selected_bands':list(selection)},
            'cache':{'generated_at':datetime.fromtimestamp(generated_at,timezone.utc).isoformat(),'oldest_tile_age_seconds':round(max(0,store.clock()-generated_at),1),'ttl_seconds':TTL,'hits':hits,'misses':misses}}
        result['cache']['inventory']=cache_status(store,start=start,end=end,zoom=zoom,bbox=bbox,bands=bands)
        store.last_query=diagnostics
        basic={k:diagnostics[k] for k in ('cached','query_seconds','lock_wait_seconds','aggregated_rows_read','returned_cells','requested_zoom','display_zoom','tile_cache_hits','tile_cache_misses')}
        print('[INFO] Density tile view '+json.dumps(basic),flush=True)
        if getattr(store,'verbose_logging',False):print('[DEBUG] Density tile view '+json.dumps(diagnostics),flush=True)
        return result


def cache_status(store,start=None,end=None,zoom=17,bbox=None,bands='all',**ignored):
    """Metadata only: never query observations or rebuild parent grids."""
    from traffic_density import selected_bands
    selection=selected_bands(bands)
    if type(zoom) is not int or not 0<=zoom<=17:raise ValueError('invalid zoom')
    today=datetime.fromtimestamp(store.clock(),timezone.utc).date()
    start=date.fromisoformat(start).isoformat() if start else (today-timedelta(days=29)).isoformat()
    end=date.fromisoformat(end).isoformat() if end else today.isoformat()
    if start>end:raise ValueError('invalid date window')
    if bbox is None:return {'cached':0,'to_build':0,'stale':0,'cacheable':False,'ttl_seconds':TTL}
    if len(bbox)!=4 or not all(math.isfinite(v) for v in bbox) or not(-180<=bbox[0]<=bbox[2]<=180 and -90<=bbox[1]<=bbox[3]<=90):raise ValueError('invalid bbox')
    tile_zoom=max(0,zoom-5);n=1<<tile_zoom
    xmin=max(0,math.ceil((bbox[0]+180)/360*n)-1);xmax=min(n-1,math.floor((bbox[2]+180)/360*n))
    ymin=max(0,math.ceil((90-bbox[3])/180*n)-1);ymax=min(n-1,math.floor((90-bbox[1])/180*n))
    total=(xmax-xmin+1)*(ymax-ymin+1)
    if total>MAX_TILES:return {'cached':0,'to_build':0,'stale':0,'cacheable':False,'ttl_seconds':TTL}
    result={'cached':0,'to_build':0,'stale':0,'cacheable':True,'ttl_seconds':TTL}
    with store.lock:
        now=store.clock()
        for x in range(xmin,xmax+1):
            for y in range(ymin,ymax+1):
                key=(store.source_type,start,end,tuple(selection),zoom,tile_zoom,x,y,store.restore_epoch)
                entry=store.tile_cache.get(key)
                result['to_build' if entry is None else 'stale' if now<entry['generated'] or now-entry['generated']>=TTL else 'cached']+=1
    return result
