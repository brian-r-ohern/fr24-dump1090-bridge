import contextlib
import importlib.util
import io
import random
import sys
import tempfile
import unittest
from pathlib import Path
from datetime import datetime,timezone
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'fr24-dump1090'))
from traffic_density import DensityStore
from density_baseline_sql import BASELINE_SQL
# A reference executor keeps old aggregation SQL while exercising all production
# viewport/date/band/cache/post-filter paths in the same query method.
import traffic_density
class DensitySqlTests(unittest.TestCase):
    def test_reference_sql_matches_numeric_viewport_query(self):
        now=datetime(2026,10,12,tzinfo=timezone.utc).timestamp()
        with tempfile.TemporaryDirectory() as folder:
            store=DensityStore(folder,clock=lambda:now,source_type='sbs_30003')
            try:
                rng=random.Random(423)
                positions=[{'hex':str(i),'lat':rng.uniform(-85,85),'lon':rng.uniform(-179,179),'alt_baro':rng.choice([None,-200,1199,1200,17999,18000,42000])} for i in range(120)]
                positions += [{'hex':'edge'+str(i),'lat':lat,'lon':lon,'alt_baro':12000} for i,(lat,lon) in enumerate([(0,0),(90,180),(-90,-180),(42,-77),(42.001,-77.001)])]
                for offset in (0,-86400,-12*86400):
                    store.observe(positions,now+offset,'sbs_30003')
                # Use a SQLite connection wrapper to execute the independent old SQL
                # whenever the new SELECT is reached; parameters retain same order.
                class ReferenceConnection:
                    def __init__(self,db):self.db=db
                    def execute(self,sql,params=()):
                        if sql.startswith('SELECT ? ||'):sql=BASELINE_SQL
                        return self.db.execute(sql,params)
                    def __getattr__(self,k):return getattr(self.db,k)
                original=dict(store.connections)
                for zoom in (0,8,11,17):
                    for bbox in (None,[-180,-90,180,90],[-77.01,41.99,-76.99,42.01],[-.01,-.01,.01,.01],[100,80,100.1,80.1]):
                        for bands in ('all','low','middle,high','none'):
                            kwargs=dict(zoom=zoom,bbox=bbox,bands=bands,max_cells=10,bypass_cache=True)
                            with contextlib.redirect_stdout(io.StringIO()):actual=store.query(**kwargs)
                            store._rollups_enabled=False
                            store.connections={k:ReferenceConnection(v) for k,v in original.items()}
                            try:
                                with contextlib.redirect_stdout(io.StringIO()):expected=store.query(**kwargs)
                            finally:
                                store.connections=original
                                store._rollups_enabled=True
                            self.assertEqual(actual['cells'],expected['cells'],(zoom,bbox,bands))
                            self.assertEqual(actual['display_zoom'],expected['display_zoom'])
                store.verbose_logging=True
                with contextlib.redirect_stdout(io.StringIO()):result=store.query(zoom=17,bbox=[-78,41,-76,43],bypass_cache=True)
                month=result['diagnostics']['monthly_queries'][0]
                self.assertEqual(month['query_strategy'],'viewport_first_numeric')
                self.assertIn('cell_locations_xy',month['query_plan'][0])
                self.assertTrue(any('cell=?' in x and 'day' in x for x in month['query_plan']))
            finally:store.close()
