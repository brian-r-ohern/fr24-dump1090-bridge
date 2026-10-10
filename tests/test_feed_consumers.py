import importlib
import json
import os
from pathlib import Path
import sys
import tempfile
import threading
import unittest
from urllib.request import urlopen
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'fr24-dump1090'))
from feed_consumers import FeedConsumers

class ConsumerTests(unittest.TestCase):
    def test_polling_identity_expiry_and_privacy(self):
        now=[0.0];store=FeedConsumers(clock=lambda:now[0],wall_clock=lambda:1720000000+now[0])
        store.record('gateway','same-agent','tracker')
        now[0]=10;store.record('gateway','same-agent','tracker')
        store.record('gateway','same-agent','skyvista');store.record('proxy','browser','bridge-map')
        snap=store.snapshot();self.assertEqual((snap['external_count'],snap['internal_count']),(2,1))
        self.assertFalse(snap['count_is_estimate'])
        self.assertEqual(next(c for c in snap['clients'] if c['label']=='tracker')['mean_poll_interval_seconds'],10)
        self.assertNotIn('gateway',json.dumps(snap));now[0]=70;self.assertEqual(store.snapshot()['recent_count'],0)
    def test_ambiguous_clients_invalid_ids_and_capacity(self):
        store=FeedConsumers(limit=2)
        store.record('gateway','agent');store.record('gateway','agent')
        self.assertEqual(store.snapshot()['external_count'],1);self.assertTrue(store.snapshot()['count_is_estimate'])
        store.record('gateway','other','<script>');self.assertEqual(store.snapshot()['external_count'],2)
        store.record('third','third');self.assertEqual(store.snapshot()['recent_count'],2)
        self.assertNotIn('<script>',json.dumps(store.snapshot()))
    def test_actual_http_routes_and_all_source_status(self):
        with tempfile.TemporaryDirectory() as directory:
            options=Path(directory)/'options.json';options.write_text('{"receiver_host":"localhost"}')
            os.environ.setdefault('FR24_OPTIONS_PATH',str(options))
            b=importlib.import_module('fr24_dump1090')
            old=b.feed_consumers;b.feed_consumers=FeedConsumers()
            server=b.ThreadingHTTPServer(('127.0.0.1',0),b.Handler)
            thread=threading.Thread(target=server.serve_forever,daemon=True);thread.start()
            base='http://127.0.0.1:'+str(server.server_port)
            try:
                for path in ['/health','/status','/data/aircraft.json?client_id=tracker','/aircraft.json?client_id=skyvista','/data/aircraft.json?client_id=bridge-map']:
                    with urlopen(base+path) as response: response.read()
                with urlopen(base+'/status') as response: status=json.load(response)
                self.assertEqual(status['feed_consumers']['recent_count'],3)
                with urlopen(base+'/status-page') as response: self.assertIn('Feed dependencies',response.read().decode())
                with urlopen(base+'/') as response:
                    page=response.read().decode();self.assertIn('client_id=bridge-map',page);self.assertIn('aircraft-bridge-navigation',page)
                cfg=dict(b.CFG)
                try:
                    for source in b.VALID_SOURCES:
                        b.CFG['source']=source
                        self.assertIn('feed_consumers',b.snapshot_status())
                finally:b.CFG.clear();b.CFG.update(cfg)
            finally:
                server.shutdown();server.server_close();thread.join();b.feed_consumers=old
