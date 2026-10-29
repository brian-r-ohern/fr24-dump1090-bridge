import math,sys,unittest
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'fr24-dump1090'))
from home_pass import home_passes
class HomePassTests(unittest.TestCase):
 def payload(self,altitude=5000,speed=120,offset=0,now=60,vertical=0):
  # Northbound, 5 NM south at display time; position support at t=0,30,60.
  rows=[]
  for t in (0,30,60):
   rows.append({'t':t,'lat':(-5*1852+speed*(t-60))/111195,'lon':offset/111195,'alt_baro':altitude+vertical*(t-60),'segment':1,'reported_speed_knots':speed/.514444})
  return {'source':'sbs_30003','generated_at':now,'tracks':{'a':{'samples':rows}}}
 def test_approach_and_high_altitude_exclusion(self):
  home={'latitude':0,'longitude':0,'elevation_m':0}
  result=home_passes(self.payload(),home)['a'];self.assertAlmostEqual(result['seconds'],77.2,delta=.3);self.assertLess(result['slant_nm'],1)
  self.assertEqual(home_passes(self.payload(altitude=25000),home),{})
 def test_elevation_missing_altitude_stale_and_opening(self):
  home={'latitude':0,'longitude':0,'elevation_m':0}
  self.assertEqual(home_passes(self.payload(),{**home,'elevation_m':None}),{})
  p=self.payload(now=100);self.assertEqual(home_passes(p,home),{})
  p=self.payload()
  for r in p['tracks']['a']['samples']:r['alt_baro']=None
  self.assertEqual(home_passes(p,home),{})
  p=self.payload()
  for r in p['tracks']['a']['samples']:r['lat']+=20*1852/111195
  self.assertEqual(home_passes(p,home),{})
 def test_slant_not_horizontal_and_horizon(self):
  home={'latitude':0,'longitude':0,'elevation_m':0}
  self.assertEqual(home_passes(self.payload(altitude=16000,offset=2*1852),home),{})
  p=self.payload(speed=31*.514444);r=home_passes(p,home)['a'];self.assertTrue(r['horizon_limited']);self.assertEqual(r['seconds'],300)
 def test_descent_and_source_eligibility(self):
  home={'latitude':0,'longitude':0,'elevation_m':0}
  self.assertTrue(home_passes(self.payload(altitude=19000,vertical=-20),home))
  p=self.payload();p['source']='swim_tfms';self.assertEqual(home_passes(p,home),{})
if __name__=='__main__':unittest.main()

class HomePassIntegrationTests(unittest.TestCase):
 def test_motion_payload_attaches_prediction_without_home_coordinates(self):
  from unittest.mock import patch,Mock
  import test_density_bridge as fixture
  bridge=fixture.bridge
  payload=HomePassTests().payload()
  with patch.object(bridge,'home_marker',{'latitude':0,'longitude':0,'elevation_m':0}),patch.object(bridge,'get_motion_engine',return_value=Mock(snapshot=Mock(return_value={'aircraft':{'a':{'quality':'supported'}}}))),patch.object(bridge.track_history,'kinematic_snapshot',return_value=payload):
   result=bridge.map_motion_snapshot()
  self.assertIn('home_pass',result['aircraft']['a'])
  self.assertNotIn('latitude',str(result));self.assertNotIn('longitude',str(result))
