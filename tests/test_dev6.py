import gzip,json,tempfile,threading,time,unittest
from pathlib import Path
from urllib.request import urlopen
from urllib.error import HTTPError
from unittest.mock import patch
from test_density_bridge import bridge
from traffic_density import DensityStore

class FAAAnalyticalExports(unittest.TestCase):
 def test_downloads_and_feed_isolation(self):
  for source in ('swim_tfms','swim_sfdps'):
   with tempfile.TemporaryDirectory() as tmp:
    store=DensityStore(Path(tmp),source_type=source)
    store.observe([{'hex':'x','lat':42,'lon':-77,'alt_baro':10000}])
    with patch.dict(bridge.CFG,source=source),patch.object(bridge,'density_store',store):
     server=bridge.ThreadingHTTPServer(('127.0.0.1',0),bridge.Handler);thread=threading.Thread(target=server.serve_forever,daemon=True);thread.start()
     try:
      base=f'http://127.0.0.1:{server.server_port}'
      response=urlopen(base+'/traffic-density/export?compression=gzip');self.assertIn('.json.gz',response.headers['Content-Disposition']);self.assertEqual(json.loads(gzip.decompress(response.read()))['source_type'],source)
      page=urlopen(base+'/status-page').read().decode();self.assertNotIn('FAA exports disabled',page);self.assertIn('traffic-density/export?compression=gzip',page)
      for path in ('/aircraft.json','/data/aircraft.json','/track-history','/motion','/traffic-density/view','/traffic-density'):
       with self.assertRaises(HTTPError) as error:urlopen(base+path)
       self.assertEqual(error.exception.code,403)
      with patch.dict(bridge.CFG,trusted_networks='192.168.0.0/24'):
       with self.assertRaises(HTTPError) as error:urlopen(base+'/traffic-density/export')
       self.assertEqual(error.exception.code,403)
     finally:server.shutdown();server.server_close();thread.join();store.close()
