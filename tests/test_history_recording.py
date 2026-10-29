import gzip,json,sys,tempfile,threading,time,unittest
from pathlib import Path
from unittest.mock import patch
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'fr24-dump1090'))
from history_recording import HistoryRecorder,DAY
from track_history import TrackHistory
from history_geojson import history_from_geojson
BASE=1792950000
class RecordingTests(unittest.TestCase):
 def setUp(self):
  self.tmp=tempfile.TemporaryDirectory();self.now=[BASE];self.rec=HistoryRecorder(self.tmp.name,'sbs_30003','test',clock=lambda:self.now[0]);self.rec.start()
 def tearDown(self):self.rec.close();self.tmp.cleanup()
 def sample(self,t,lat=43.0):
  self.now[0]=BASE+t
  return self.rec.record([{'hex':'abc123','flight':'TEST','lat':lat,'lon':-75,'gs':120,'seen_pos':0,'alt_baro':1000}],self.now[0],self.now[0],{'abc123':{'position_time':self.now[0],'alt_baro_time':self.now[0],'altitude_reference':'reported'}},{'process_rss_bytes':123456})
 def export_json(self,format='geojson'):
  path=self.rec.export(format)
  try:
   with gzip.open(path,'rt') as f:return json.load(f) if format=='geojson' else [json.loads(line) for line in f]
  finally:path.unlink()
 def test_unsampled_snapshots_distinct_positions_and_geojson_metadata(self):
  for t in (0,1,2,12):self.assertTrue(self.sample(t,43+t*.0001))
  raw=self.export_json('jsonl');self.assertEqual(len(raw),5);self.assertIn('field_metadata',self.export_json()['features'][0]['properties']['record']['samples'][0])
  result=history_from_geojson(self.export_json());rows=result['tracks']['abc123']['samples'];self.assertEqual(len(rows),4)
  self.assertEqual(rows[1]['t']-rows[0]['t'],1);self.assertEqual(rows[0]['field_metadata']['altitude_reference'],'reported')
  self.assertEqual(raw[1]['resources']['process_rss_bytes'],123456)
 def test_duplicate_positions_raw_retained_once_in_geojson(self):
  self.sample(0);self.rec.record([{'hex':'abc123','lat':43,'lon':-75,'seen_pos':1}],BASE+1,BASE+1)
  self.rec.flush();self.assertEqual(self.rec.status()['retained_snapshots'],2);self.assertEqual(self.rec.status()['retained_samples'],1)
 def test_restart_resume_original_deadline_and_gap(self):
  self.sample(0);self.rec.flush();end=self.rec.ends_at;self.rec.close()
  self.rec=HistoryRecorder(self.tmp.name,'sbs_30003','test',clock=lambda:self.now[0]);self.assertTrue(self.rec.enabled);self.assertEqual(self.rec.ends_at,end)
  self.sample(120);self.rec.flush();rows=history_from_geojson(self.export_json())['tracks']['abc123']['samples'];self.assertEqual(rows[-1]['break_reason'],'observation_gap');self.assertEqual(rows[-1]['segment'],2)
 def test_retention_auto_stop_and_source_isolation(self):
  self.sample(0);self.rec.flush();self.now[0]=BASE+DAY+1
  self.assertFalse(self.sample(DAY+1));self.assertFalse(self.rec.status()['enabled']);self.assertEqual(self.rec.status()['retained_samples'],1)
  self.rec.start();self.sample(DAY+2);self.rec.flush();self.assertEqual(self.rec.status()['retained_samples'],1)
  other=HistoryRecorder(self.tmp.name,'swim_sfdps','test',clock=lambda:self.now[0]);self.assertEqual(other.status()['retained_samples'],0);other.close()
 def test_stop_export_and_storage_limit(self):
  self.sample(0);self.rec.stop();self.assertFalse(self.sample(1));self.assertEqual(len(self.export_json()['features']),1)
  self.rec.start();self.rec.max_bytes=0;self.sample(2);self.rec.flush();state=self.rec.status();self.assertFalse(state['enabled']);self.assertEqual(state['snapshots_dropped'],1);self.assertIn('storage limit',state['last_error'])
 def test_queue_limit_is_visible(self):
  self.rec.queue_limit=0;self.assertFalse(self.sample(0));self.assertEqual(self.rec.status()['snapshots_dropped'],1)
 def test_normal_history_default_and_ram_estimate(self):
  h=TrackHistory('sbs_30003',clock=lambda:BASE+12)
  for t in (0,1,12):h.observe([{'hex':'x','lat':43,'lon':-75,'seen_pos':0}],BASE+t)
  self.assertEqual(len(h.snapshot()['tracks']['x']['samples']),2)
  status=h.resource_status();self.assertEqual(status['retained_samples'],2);self.assertGreater(status['estimated_memory_bytes'],0)
 def test_replay_export(self):
  for t in (0,12,24):self.sample(t)
  path=self.rec.export('jsonl')
  try:
   import importlib.util
   spec=importlib.util.spec_from_file_location('replay_day',Path(__file__).resolve().parents[1]/'tools/replay_recording.py');m=importlib.util.module_from_spec(spec);spec.loader.exec_module(m)
   self.assertEqual(m.replay(path)['snapshots_replayed'],3)
  finally:path.unlink()

class RecordingHttpTests(unittest.TestCase):
 def test_actual_routes_collection_and_faa_isolation(self):
  from test_density_bridge import bridge as b
  from motion_state import MotionEngine
  from urllib.request import Request,urlopen
  from urllib.error import HTTPError
  for source in ('sbs_30003','swim_sfdps'):
   with self.subTest(source=source),tempfile.TemporaryDirectory() as folder:
    recorder=HistoryRecorder(folder,source,'test')
    with patch.dict(b.CFG,source=source),patch.object(b,'get_recorder',return_value=recorder),patch.object(b,'track_history',TrackHistory(source)),patch.object(b,'motion_engine',MotionEngine(source)),patch.object(b,'density_store',None):
     server=b.ThreadingHTTPServer(('127.0.0.1',0),b.Handler);thread=threading.Thread(target=server.serve_forever,daemon=True);thread.start();url='http://127.0.0.1:'+str(server.server_port)
     try:
      def request(path,post=False):
       return urlopen(Request(url+path,data=b'{}' if post else None,headers={'Content-Type':'application/json'}),timeout=10)
      self.assertFalse(json.load(request('/recording'))['enabled'])
      self.assertTrue(json.load(request('/recording/start',True))['enabled'])
      now=time.time();b.collect_snapshot([{'hex':'abc123','lat':43,'lon':-75,'gs':150,'seen_pos':0}],now,now,{'abc123':{'position_time':now}})
      recorder.flush();self.assertEqual(json.load(request('/recording'))['retained_samples'],1)
      for fmt in ('geojson','jsonl'):
       response=request('/recording/export?download=1&format='+fmt)
       self.assertEqual(response.headers.get_content_type(),'application/gzip');self.assertIn('attachment',response.headers['Content-Disposition'])
       text=gzip.decompress(response.read()).decode();self.assertIn('abc123',text)
       if fmt=='geojson':self.assertEqual(json.loads(text)['features'][0]['properties']['source'],source)
      with self.assertRaises(HTTPError) as err:request('/recording/export')
      self.assertEqual(err.exception.code,400)
      if source=='swim_sfdps':
       with self.assertRaises(HTTPError) as err:request('/aircraft.json')
       self.assertEqual(err.exception.code,403)
      with patch.dict(b.CFG,trusted_networks='192.168.99.0/24'):
       with self.assertRaises(HTTPError) as err:request('/recording/start',True)
       self.assertEqual(err.exception.code,403)
      self.assertFalse(json.load(request('/recording/stop',True))['enabled'])
     finally:server.shutdown();server.server_close();thread.join();recorder.close()
