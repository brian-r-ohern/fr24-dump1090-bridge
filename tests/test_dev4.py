import gzip,io,json,sys,tempfile,unittest,zipfile
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'fr24-dump1090'))
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'tools'))
from airport_context import classify_airport_context
from airport_lookup import AirportLookup
from replay_aircraft_history import load_history
import test_density_archives as archives
from test_density_archives import SmallReads
from density_archive import archive_file,restore_stream

class CompressionTests(archives.DensityArchiveTests):
 def test_gzip_roundtrip_and_truncation(self):
  with archive_file(self.store,compressed=True) as path:data=path.read_bytes()
  self.assertEqual(json.loads(gzip.decompress(data))['source_type'],'sbs_30003')
  self.assertEqual(restore_stream(self.store,SmallReads(data),len(data))['retained'],1)
  with self.assertRaises(ValueError):restore_stream(self.store,io.BytesIO(data[:-5]),len(data)-5)
 def test_gzip_source_validation(self):
  payload=self.store.export();payload['source_type']='swim_tfms';data=gzip.compress(json.dumps(payload).encode())
  with self.assertRaisesRegex(ValueError,'source'):restore_stream(self.store,io.BytesIO(data),len(data))

class AirportContextTests(unittest.TestCase):
 def setUp(self):
  self.temp=tempfile.TemporaryDirectory();self.path=Path(self.temp.name)/'airports.json'
  self.path.write_text(json.dumps([dict(icao='KAAA',iata='AAA',lat=42,lon=-77,elevation_ft=500)]));self.airports=AirportLookup(self.path)
 def tearDown(self):self.temp.cleanup()
 def samples(self,depart=False,altitude=5000):
  return [dict(t=t,lat=42+(i if depart else 6-i)*.02,lon=-77,segment=1,alt_baro=altitude+(i*300 if depart else -i*300),motion={}) for i,t in enumerate(range(0,121,20))]
 def test_approach_departure_and_unknown_route(self):
  self.assertEqual(classify_airport_context({'route_destination':'AAA'},self.samples(),self.airports)['name'],'likely_approach')
  self.assertEqual(classify_airport_context({'route_origin':'KAAA'},self.samples(True),self.airports)['name'],'likely_departure')
  self.assertIsNone(classify_airport_context({},self.samples(),self.airports))
 def test_altitude_gap_and_elevation_limits(self):
  self.assertIsNone(classify_airport_context({'destination':'KAAA'},self.samples(altitude=35000),self.airports))
  rows=self.samples();rows[-1]['segment']=2
  self.assertIsNone(classify_airport_context({'destination':'KAAA'},rows,self.airports))
  self.path.write_text(json.dumps([dict(icao='KAAA',lat=42,lon=-77)]));self.airports=AirportLookup(self.path)
  self.assertIsNone(classify_airport_context({'destination':'KAAA'},self.samples(),self.airports))
 def test_context_keeps_geometry(self):
  rows=self.samples(altitude=2500)
  for i,row in enumerate(rows):row['motion']={'patterns':[{'name':'course_reversal','first_supported':0 if i<3 else 60,'evidence':{'turn_degrees':180}}]}
  original=json.dumps(rows);result=classify_airport_context({},rows,self.airports)
  self.assertEqual(result['name'],'possible_airport_circuit');self.assertEqual(json.dumps(rows),original)
  rows[-1]['motion']['quality']='stale';self.assertIsNone(classify_airport_context({},rows,self.airports))

class ReplayInputTests(unittest.TestCase):
 def test_plain_gzip_zip(self):
  payload={'schema_version':1,'tracks':{},'source':'sbs_30003'}
  with tempfile.TemporaryDirectory() as tmp:
   p=Path(tmp)/'history';p.write_text(json.dumps(payload));self.assertEqual(load_history(p),payload)
   p.write_bytes(gzip.compress(json.dumps(payload).encode()));self.assertEqual(load_history(p),payload)
   with zipfile.ZipFile(p,'w') as z:z.writestr('recording.json',json.dumps(payload))
   self.assertEqual(load_history(p),payload)
   with zipfile.ZipFile(p,'a') as z:z.writestr('second.json','{}')
   with self.assertRaises(ValueError):load_history(p)

class DownloadTests(unittest.TestCase):
 def test_history_gzip_attachment_and_density_stream(self):
  import threading,urllib.request,time
  from unittest.mock import patch
  from test_density_bridge import bridge as b
  from track_history import TrackHistory
  h=TrackHistory('swim_sfdps');now=time.time();h.observe([{'hex':'~x','lat':42,'lon':-77}],now,metadata={'~x':{'position_time':now}})
  with patch.dict(b.CFG,source='swim_sfdps'),patch.object(b,'track_history',h):
   server=b.ThreadingHTTPServer(('127.0.0.1',0),b.Handler);thread=threading.Thread(target=server.serve_forever,daemon=True);thread.start()
   try:
    response=urllib.request.urlopen(f'http://127.0.0.1:{server.server_port}/aircraft-history?download=1&compression=gzip')
    self.assertEqual(response.headers['Content-Type'],'application/gzip');self.assertIn('.geojson.gz',response.headers['Content-Disposition']);self.assertIn('~x',__import__('history_geojson').history_from_geojson(json.loads(gzip.decompress(response.read())))['tracks'])
   finally:server.shutdown();server.server_close();thread.join()
