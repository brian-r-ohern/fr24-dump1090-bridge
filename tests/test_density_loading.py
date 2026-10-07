import sys,time,tempfile,unittest
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'fr24-dump1090'))
from traffic_density import DensityStore
class LoadingTests(unittest.TestCase):
 def test_bounded_view_preserves_selected_counts(self):
  with tempfile.TemporaryDirectory() as folder:
   s=DensityStore(folder,source_type='sbs_30003')
   s.observe([{'hex':str(i),'lat':42+i*.003,'lon':-77+i*.003,'alt_baro':500 if i%2 else 25000} for i in range(100)])
   raw=s.query(bands='low')
   bounded=s.geojson(bands='low',max_cells=5)
   self.assertLessEqual(len(bounded['features']),5)
   self.assertEqual(sum(x['selected_observation_count'] for x in raw['cells']),sum(x['properties']['selected_observation_count'] for x in bounded['features']))
   self.assertEqual(len(s.query()['cells']),100)
   self.assertIn('query_seconds',s.status()['last_query'])
   s.close()
 def test_viewport_filter_and_clear_survive_reopen(self):
  with tempfile.TemporaryDirectory() as folder:
   s=DensityStore(folder,source_type='sbs_30003')
   s.observe([{'hex':'one','lat':42,'lon':-77,'alt_baro':500},{'hex':'two','lat':20,'lon':20,'alt_baro':25000}])
   d=s.query(bbox=[-78,41,-76,43],max_cells=6000)
   self.assertEqual(len(d['cells']),1)
   self.assertEqual(d['diagnostics']['aggregated_rows_read'],1)
   self.assertTrue(s.query(bbox=[-78,41,-76,43],bands='high',max_cells=6000)['diagnostics']['cached'])
   s.clear();self.assertEqual(s.query()['cells'],[])
   s.close();s=DensityStore(folder,source_type='sbs_30003');self.assertEqual(s.query()['cells'],[])
   s.observe([{'hex':'one','lat':42,'lon':-77}]);self.assertEqual(s.query()['cells'][0]['passage_count'],1)
   s.close()
