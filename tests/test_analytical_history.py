import sys,unittest,json,threading,urllib.request,urllib.error
from pathlib import Path
from unittest.mock import patch
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'fr24-dump1090'))
from track_history import TrackHistory,allowed_peer
from motion_patterns import detect
BASE=1700000000
class HistoryTests(unittest.TestCase):
 def test_all_sources_and_provenance(self):
  for source in ('sbs_30003','aircraft_json','flights_js','swim_tfms','swim_sfdps'):
   h=TrackHistory(source,clock=lambda:BASE+24)
   for t in (0,12,24):h.observe([{'hex':'~local','lat':42+t*.0001,'lon':-77,'gs':120,'alt_baro':4000}],BASE+t,metadata={'~local':{'position_time':BASE+t,'occurrence':'one'}})
   d=h.snapshot();rows=d['tracks']['~local']['samples'];self.assertEqual(len(rows),3);self.assertEqual(rows[1]['position_time_basis'],'source_position_time');self.assertIsNotNone(rows[1]['derived_ground_speed_knots']);self.assertTrue(d['transient'])
 def test_gaps_occurrence_discontinuity_and_out_of_order(self):
  h=TrackHistory('swim_sfdps',clock=lambda:BASE+250)
  for t,lat,occ in ((0,42,'one'),(12,42.001,'one'),(100,42.002,'one'),(112,42.003,'two'),(124,50,'two'),(120,50,'two')):
   h.observe([{'hex':'x','lat':lat,'lon':-77}],BASE+t,metadata={'x':{'position_time':BASE+t,'occurrence':occ}})
  rows=h.snapshot()['tracks']['x']['samples'];self.assertEqual(len(rows),5)
  self.assertEqual([p['break_reason'] for p in rows[2:]],['observation_gap','occurrence_change','position_discontinuity'])
  self.assertTrue(all(p['derived_ground_speed_knots'] is None for p in rows[2:]))
 def test_hour_bound_expiry_and_copy(self):
  now=[BASE];h=TrackHistory('sbs_30003',clock=lambda:now[0])
  for t in range(0,7200,10):
   now[0]=BASE+t;h.observe([{'hex':'x','lat':42,'lon':-77,'seen_pos':0}],now[0])
  d=h.snapshot();self.assertLessEqual(len(d['tracks']['x']['samples']),360)
  d['tracks']['x']['samples'][0]['lat']=0;self.assertEqual(h.snapshot()['tracks']['x']['samples'][0]['lat'],42)
  now[0]+=3601;self.assertEqual(h.snapshot()['tracks'],{})
 def test_network_boundaries(self):
  for address in ('127.0.0.1','192.168.0.42','172.30.32.1','::1','::ffff:192.168.0.2'):self.assertTrue(allowed_peer(address))
  for address in ('8.8.8.8','169.254.1.2','2001:4860:4860::8888','bad'):self.assertFalse(allowed_peer(address))
  self.assertFalse(allowed_peer('192.168.1.2','192.168.0.0/24'));self.assertFalse(allowed_peer('127.0.0.1','invalid'))
 def test_diagnostic_gates(self):
  d={};self.assertEqual(detect([],d),[]);self.assertEqual(d,{'insufficient_history':1})
 def test_routes_faa_export_and_restream_guard(self):
  from test_density_bridge import bridge as b
  h=TrackHistory('swim_sfdps');now=h.clock();h.observe([{'hex':'~x','icao_address':'abc123','lat':42,'lon':-77,'gs':200}],now,metadata={'~x':{'position_time':now}})
  with patch.dict(b.CFG,source='swim_sfdps'),patch.object(b,'track_history',h):
   server=b.ThreadingHTTPServer(('127.0.0.1',0),b.Handler);thread=threading.Thread(target=server.serve_forever,daemon=True);thread.start()
   try:
    url='http://127.0.0.1:'+str(server.server_port)
    response=urllib.request.urlopen(url+'/aircraft-history?keys=~x&download=1');self.assertIn('attachment',response.headers['Content-Disposition']);self.assertIn('~x',__import__('history_geojson').history_from_geojson(json.load(response))['tracks'])
    self.assertIn('~x',json.load(urllib.request.urlopen(url+'/aircraft-history?hex=abc123'))['tracks'])
    for path,code in (('/aircraft-history',400),('/aircraft-history?keys=bad!',400),('/aircraft.json',403),('/track-history',403)):
     with self.assertRaises(urllib.error.HTTPError) as err:urllib.request.urlopen(url+path)
     self.assertEqual(err.exception.code,code)
    with patch.dict(b.CFG,trusted_networks='192.168.0.0/24'):
     with self.assertRaises(urllib.error.HTTPError) as err:urllib.request.urlopen(url+'/aircraft-history?keys=~x')
     self.assertEqual(err.exception.code,403)
   finally:server.shutdown();server.server_close();thread.join()
if __name__=='__main__':unittest.main()

class ReplayTests(unittest.TestCase):
 def test_orbit_replay_and_recorded_segment_boundaries(self):
  import importlib.util
  from test_motion_patterns import orbit
  spec=importlib.util.spec_from_file_location('history_replay',Path(__file__).resolve().parents[1]/'tools/replay_aircraft_history.py');module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module)
  samples=[{**p,'segment':1,'alt_baro':10000,'reported_speed_knots':300} for p in orbit()]
  payload={'schema_version':1,'source':'swim_sfdps','tracks':{'~x':{'samples':samples}}}
  result=module.replay(payload)['observations'];self.assertEqual(len(result),len(samples));self.assertEqual(result[-1]['state']['patterns'][0]['name'],'repeated_orbit');self.assertEqual(result[0]['state']['patterns'],[])
  for p in samples[len(samples)//2:]:p['segment']=2;p['break_reason']='observation_gap'
  result=module.replay(payload)['observations'];self.assertFalse(any(p['name']=='repeated_orbit' for p in result[-1]['state']['patterns']))
