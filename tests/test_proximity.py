import math,socket,sys,unittest
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'fr24-dump1090'))
from proximity import proximity_view,EARTH
from sbs_transport import received_chunks
BASE=1700000000

def track(x,y,vx,vy,alt=10000,rate=0,end=0,basis='alt_baro',maneuver=False):
 rows=[]
 for t in (-60,-30,0):
  offset=t+end
  rows.append(dict(t=BASE+offset,lat=42+math.degrees((y+vy*t)/EARTH),lon=-77+math.degrees((x+vx*t)/(EARTH*math.cos(math.radians(42)))),segment=1,alt_baro=None,alt_geom=None,reported_speed_knots=math.hypot(vx,vy)/.514444))
  rows[-1][basis]=None if alt is None else alt+rate*t
 rows[-1]['motion']={'primitives':[{'name':'turning_left'}] if maneuver else [],'patterns':[]}
 return {'identity':{'flight':'TEST'},'samples':rows}
def view(a,b,source='aircraft_json',now=BASE):return proximity_view({'generated_at':now,'source':source,'tracks':{'a':a,'b':b}},'a',radius_nm=20)
class PairTests(unittest.TestCase):
 def test_default_ten_nm_gate(self):
  payload={'generated_at':BASE,'source':'aircraft_json','tracks':{'a':track(0,0,0,0),'near':track(9.9*1852,0,0,0),'far':track(10.1*1852,0,0,0)}}
  result=proximity_view(payload,'a')
  self.assertEqual(result['radius_nm'],10)
  self.assertEqual([p['track_id'] for p in result['pairs']],['near'])

 def test_head_on_cpa_and_vertical(self):
  p=view(track(0,0,100,0),track(20000,0,-100,0,alt=12000,rate=-10))['pairs'][0]
  self.assertAlmostEqual(p['tcpa_seconds'],100,delta=.1);self.assertLess(p['cpa_nm'],.01);self.assertEqual(p['trend'],'closing');self.assertEqual(p['vertical_ft'],2000);self.assertAlmostEqual(p['vertical_at_cpa_ft'],1000,delta=1)
 def test_crossing_and_opening(self):
  p=view(track(-10000,0,100,0),track(0,-10000,0,100))['pairs'][0];self.assertLess(p['cpa_nm'],.01)
  p=view(track(0,0,-100,0),track(10000,0,100,0))['pairs'][0];self.assertEqual(p['trend'],'opening');self.assertIsNone(p['tcpa_seconds'])
 def test_horizon_and_parallel(self):
  p=view(track(0,0,1,0),track(10000,0,-1,0))['pairs'][0];self.assertTrue(p['horizon_limited']);self.assertEqual(p['tcpa_seconds'],300)
  p=view(track(0,0,100,0),track(1000,0,100,0))['pairs'][0];self.assertIsNone(p['cpa_nm']);self.assertEqual(p['prediction_reason'],'relative_velocity_too_small')
 def test_unknown_reference_and_stale(self):
  self.assertIsNone(view(track(0,0,100,0),track(1000,0,-100,0,alt=None))['pairs'][0]['vertical_ft'])
  self.assertIsNone(view(track(0,0,100,0),track(1000,0,-100,0,basis='alt_geom'))['pairs'][0]['vertical_ft'])
  self.assertEqual(view(track(0,0,100,0),track(1000,0,-100,0),now=BASE+46)['reason'],'selected_position_missing_or_stale')
 def test_common_time_and_maneuver(self):
  p=view(track(0,0,100,0,end=-10,maneuver=True),track(10000,0,-100,0))['pairs'][0];self.assertAlmostEqual(p['horizontal_nm'],9000/1852,delta=.01);self.assertEqual(p['alignment_seconds'],10);self.assertIn('maneuvering',p['quality'])
 def test_gap_and_insufficient_velocity(self):
  a=track(0,0,100,0);a['samples'][-1]['segment']=2
  p=view(a,track(1000,0,-100,0))['pairs'][0];self.assertEqual(p['quality'],'insufficient_velocity');self.assertIsNone(p['tcpa_seconds'])
 def test_source_exclusion(self):
  for source in ('swim_tfms','flights_js'):self.assertEqual(view(track(0,0,0,0),track(1000,0,0,0),source)['reason'],'source_precision_or_cadence_excluded')
class SocketTests(unittest.TestCase):
 def test_silence_and_byte_reset(self):
  now=[0];events=[(30,socket.timeout()),(31,b'invalid bytes'),(80,socket.timeout()),(92,socket.timeout())]
  class Sock:
   def recv(self,n):
    now[0],value=events.pop(0)
    if isinstance(value,Exception):raise value
    return value
  g=received_chunks(Sock(),clock=lambda:now[0]);self.assertEqual(next(g),b'invalid bytes')
  with self.assertRaisesRegex(TimeoutError,'idle'):next(g)
 def test_eof_and_network_error(self):
  class Sock:
   def recv(self,n):return b''
  with self.assertRaises(ConnectionError):next(received_chunks(Sock()))

class HTTPAndReplayTests(unittest.TestCase):
 def test_selected_api_and_feed_restriction(self):
  import threading,json
  from unittest.mock import patch,Mock
  from urllib.request import urlopen
  from urllib.error import HTTPError
  from test_density_bridge import bridge as b
  history=Mock();history.kinematic_snapshot.return_value={'generated_at':BASE,'source':'swim_sfdps','tracks':{'a':track(0,0,100,0),'b':track(15000,0,-100,0)}}
  with patch.object(b,'track_history',history),patch.dict(b.CFG,source='swim_sfdps'):
   server=b.ThreadingHTTPServer(('127.0.0.1',0),b.Handler);thread=threading.Thread(target=server.serve_forever,daemon=True);thread.start()
   try:
    base=f'http://127.0.0.1:{server.server_port}'
    self.assertEqual(len(json.load(urlopen(base+'/aircraft-proximity?track_id=a'))['pairs']),1)
    for route,code in (('/aircraft-proximity',400),('/aircraft.json',403)):
     with self.assertRaises(HTTPError) as error:urlopen(base+route)
     self.assertEqual(error.exception.code,code)
   finally:server.shutdown();server.server_close();thread.join()
 def test_replay_never_uses_future_or_crosses_gap(self):
  sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'tools'))
  from replay_proximity import replay_proximity
  a=track(0,0,100,0);b=track(15000,0,-100,0)
  payload={'source':'aircraft_json','tracks':{'a':a,'b':b}}
  result=replay_proximity(payload,'a')
  self.assertTrue(all(not frame['pairs'] or frame['pairs'][0]['quality']=='insufficient_velocity' for frame in result['frames'][:2]))
  self.assertAlmostEqual(result['frames'][-1]['pairs'][0]['tcpa_seconds'],75,delta=.1)

class ReaderRecoveryTests(unittest.TestCase):
 def test_idle_socket_closed_and_new_connection_processes_bytes(self):
  from unittest.mock import patch,MagicMock
  from test_density_bridge import bridge as b
  first=MagicMock();second=MagicMock();first.__enter__.return_value=first;second.__enter__.return_value=second
  def chunks(sock, **kwargs):
   if sock is first:raise TimeoutError('SBS input idle for 60s; reconnecting')
   yield b'MSG,test\n'
   raise KeyboardInterrupt()
  with patch.multiple(b,sbs_connected=False,sbs_reconnects=0,sbs_connection_attempts=0,sbs_total_messages=0,sbs_last_message_time=0),patch.object(b.socket,'create_connection',side_effect=[first,second]) as connect,patch.object(b,'received_chunks',side_effect=chunks),patch.object(b.time,'sleep'),patch.object(b,'parse_sbs_line',return_value={'hex':'test'}),patch.object(b,'apply_sbs_update') as apply:
   with self.assertRaises(KeyboardInterrupt):b.sbs_reader()
   self.assertEqual(connect.call_count,2);self.assertEqual(b.sbs_reconnects,1);self.assertEqual(b.sbs_total_messages,1);apply.assert_called_once();first.__exit__.assert_called_once()
