import gzip,json,math,socket,sys,tempfile,unittest
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'fr24-dump1090'))
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'tools'))
from history_geojson import history_geojson,history_from_geojson
from replay_aircraft_history import load_history
from proximity import proximity_view
from sbs_transport import MessageWatchdog,received_chunks
from test_proximity import track,BASE

class GeoJSONTests(unittest.TestCase):
 def test_roundtrip_all_fields_and_segment_geometry(self):
  samples=[dict(t=t,lat=42,lon=lon,segment=seg,alt_baro=None,extra={'nested':[1,False,None]}) for t,lon,seg in [(0,179,1),(10,179.5,1),(20,-179,1),(40,-178,2),(50,-177,2),(100,-176,2)]]
  p={'schema_version':1,'source':'swim_sfdps','generated_at':101,'motion':{'events':[1]},'unknown_future_field':{'a':2},'tracks':{'~x':{'identity':{'flight':'X','extra':'kept'},'samples':samples,'other':True},'empty':{'samples':[]},'single':{'samples':[samples[0]]}}}
  g=history_geojson(p);self.assertEqual(history_from_geojson(json.loads(json.dumps(g))),p)
  self.assertIsNone(g['features'][1]['geometry']);self.assertEqual(g['features'][2]['geometry']['type'],'MultiPoint')
  geom=g['features'][0]['geometry'];self.assertEqual(geom['type'],'GeometryCollection');self.assertEqual(len(geom['geometries'][0]['coordinates']),2);self.assertEqual(len(geom['geometries'][1]['coordinates']),2)
  with tempfile.TemporaryDirectory() as d:
   for name,data in [('new.geojson.gz',g),('old.json.gz',p)]:
    f=Path(d)/name
    with gzip.open(f,'wt') as h:json.dump(data,h)
    self.assertEqual(load_history(f),p)
 def test_invalid_coordinates_are_not_drawn_but_preserved(self):
  p={'tracks':{'x':{'samples':[{'t':1,'lat':None,'lon':1}]}}};g=history_geojson(p);self.assertIsNone(g['features'][0]['geometry']);self.assertEqual(history_from_geojson(g),p)

class SlantTests(unittest.TestCase):
 def test_sort_before_limit_and_unknown_last(self):
  tracks={'a':track(0,0,100,0),'stacked':track(100,0,100,0,alt=40000),'near':track(1000,0,100,0),'unknown':track(10,0,100,0,alt=None)}
  payload={'source':'aircraft_json','generated_at':BASE,'tracks':tracks}
  p=proximity_view(payload,'a',limit=1);self.assertEqual(p['pairs'][0]['track_id'],'near');self.assertEqual(p['selected_identity']['flight'],'TEST')
  pairs=proximity_view(payload,'a')['pairs'];self.assertEqual(pairs[-1]['track_id'],'unknown');self.assertIsNone(pairs[-1]['slant_nm']);self.assertAlmostEqual(pairs[1]['slant_nm'],math.hypot(100,30000*.3048)/1852,places=3)
 def test_reciprocal_slant_and_closure(self):
  payload={'source':'aircraft_json','generated_at':BASE,'tracks':{'a':track(0,0,100,0),'b':track(10000,0,-100,0,alt=12000)}}
  a=proximity_view(payload,'a')['pairs'][0];b=proximity_view(payload,'b')['pairs'][0];self.assertAlmostEqual(a['slant_nm'],b['slant_nm'],places=2);self.assertEqual(a['closing_knots'],b['closing_knots'])

class WatchdogTests(unittest.TestCase):
 def test_status_bytes_do_not_reset_aircraft_timer(self):
  now=[0];w=MessageWatchdog(clock=lambda:now[0])
  class Sock:
   def recv(self,n):now[0]+=20;return b'STA,status\n'
  g=received_chunks(Sock(),clock=lambda:now[0],watchdog=w)
  for _ in range(3):next(g)
  with self.assertRaisesRegex(TimeoutError,'valid MSG'):next(g)
 def test_accepted_aircraft_messages_reset_timer(self):
  now=[0];w=MessageWatchdog(clock=lambda:now[0]);now[0]=55;w.accepted();now[0]=100;w.check();now[0]=116
  with self.assertRaises(TimeoutError):w.check()
