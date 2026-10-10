"""Exercise actual HTTP routes and all four publisher collection hooks."""
import importlib
import json
import os
import sys
import tempfile
import threading
import time
import unittest
from pathlib import Path
from unittest.mock import patch
from urllib.error import HTTPError
from urllib.request import Request, urlopen
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'fr24-dump1090'))
_options=tempfile.TemporaryDirectory()
p=Path(_options.name)/'options.json';p.write_text(json.dumps({'receiver_host':'localhost'}))
os.environ['FR24_OPTIONS_PATH']=str(p)
bridge=importlib.import_module('fr24_dump1090')
from traffic_density import DensityStore

class StopCycle(Exception):pass

class DensityBridgeTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory()
        self.original_store=bridge.density_store
        self.original_cfg=dict(bridge.CFG)
        bridge.density_store=DensityStore(self.temp.name,source_type=bridge.CFG["source"])
        self.server=bridge.ThreadingHTTPServer(('127.0.0.1',0),bridge.Handler)
        self.thread=threading.Thread(target=self.server.serve_forever,daemon=True);self.thread.start()
        self.base='http://127.0.0.1:'+str(self.server.server_port)
        self.ac={'hex':'abc123','lat':42,'lon':-77,'alt_baro':5000}

    def tearDown(self):
        self.server.shutdown();self.server.server_close();self.thread.join()
        bridge.density_store.close();bridge.density_store=self.original_store
        bridge.CFG.clear();bridge.CFG.update(self.original_cfg)
        self.temp.cleanup()

    def request(self,path,payload=None):
        request=Request(self.base+path,data=json.dumps(payload).encode() if payload is not None else None,
                        headers={'Content-Type':'application/json'})
        try:
            response=urlopen(request,timeout=5)
        except HTTPError as exc:
            response=exc
        with response:
            body=response.read().decode()
            return response.status,json.loads(body) if response.headers.get_content_type() in ('application/json','application/geo+json') else body

    def test_confirmed_clear_is_selective(self):
        bridge.collect_density([self.ac],time.time())
        self.assertEqual(self.request('/data/clear',{'target':'density'})[0],400)
        self.assertEqual(len(bridge.density_store.query()['cells']),1)
        with patch.object(bridge,'clear_coverage') as coverage:
            self.assertEqual(self.request('/data/clear',{'target':'density','confirmation':'CLEAR'})[0],200)
            coverage.assert_not_called()
        self.assertEqual(bridge.density_store.query()['cells'],[])
        bridge.collect_density([self.ac],time.time())
        with patch.object(bridge,'clear_coverage') as coverage:
            self.assertEqual(self.request('/data/clear',{'target':'range','confirmation':'CLEAR'})[0],200)
            coverage.assert_called_once()
        self.assertEqual(len(bridge.density_store.query()['cells']),1)
        self.assertEqual(self.request('/data/clear',{'target':'all','confirmation':'CLEAR'})[0],400)

    def test_operation_logs_outcomes_counts_and_skip_map_polling(self):
        bridge.collect_density([self.ac],time.time())
        with patch('builtins.print') as output:
            code,backup=self.request('/traffic-density/export');self.assertEqual(code,200)
            self.assertEqual(self.request('/traffic-density/import',backup)[0],200)
            self.assertEqual(self.request('/data/clear',{'target':'density','confirmation':'CLEAR'})[0],200)
            self.assertEqual(self.request('/traffic-density/import',{})[0],400)
            self.request('/range-coverage')
            self.request('/traffic-density.geojson?zoom=12&max_cells=6000')
        records=[json.loads(call.args[0].split(' Data operation ',1)[1]) for call in output.call_args_list
                 if call.args and ' Data operation ' in str(call.args[0])]
        completed=[r for r in records if r['phase']=='completed']
        self.assertEqual([r['action'] for r in completed],['export','import','clear'])
        self.assertGreater(completed[0]['response_bytes'],0)
        self.assertEqual(completed[1]['retained'],1)
        self.assertEqual(completed[2]['target'],'density')
        self.assertTrue(any(r['phase']=='failed' and r['http_status']==400 for r in records))
        self.assertTrue(all(r['dataset']!='range-coverage' for r in records))
        self.assertTrue(all(r['source']=='sbs_30003' for r in records))
        self.assertNotIn('receiver_host',str(records))

    def test_range_download_is_logged_but_disconnected_export_is_aborted(self):
        finished = threading.Event()
        def capture_completion(*args, **kwargs):
            if args and ' Data operation ' in str(args[0]):
                record = json.loads(args[0].split(' Data operation ', 1)[1])
                if record.get('phase') == 'completed' and record.get('dataset') == 'range-coverage':
                    finished.set()
        with patch('builtins.print', side_effect=capture_completion) as output:
            self.assertEqual(self.request('/range-coverage?download=1')[0],200)
            # The HTTP body may arrive before the server thread logs completion.
            self.assertTrue(finished.wait(2), 'Server did not log export completion')
        records=[json.loads(call.args[0].split(' Data operation ',1)[1]) for call in output.call_args_list
                 if call.args and ' Data operation ' in str(call.args[0])]
        self.assertEqual(records[-1]['phase'],'completed')
        self.assertEqual(records[-1]['dataset'],'range-coverage')
        handler=object.__new__(bridge.Handler)
        handler.path='/traffic-density/export'
        def disconnected():
            handler.operation_status=200
            raise BrokenPipeError()
        with patch('builtins.print') as output:
            handler._run_operation('GET',disconnected)
        record=json.loads(output.call_args.args[0].split(' Data operation ',1)[1])
        self.assertEqual(record['phase'],'aborted')
        self.assertEqual(record['error_type'],'BrokenPipeError')

    def test_clear_all_clears_other_sources_and_range(self):
        other=DensityStore(Path(self.temp.name)/'swim_tfms',source_type='swim_tfms')
        other.observe([self.ac]);other.close()
        bridge.collect_density([self.ac],time.time())
        with patch.dict(os.environ,{'FR24_DENSITY_PATH':self.temp.name}),patch.object(bridge,'clear_coverage') as coverage:
            code,result=self.request('/data/clear',{'target':'all','confirmation':'CLEAR ALL'})
            self.assertEqual(code,200);coverage.assert_called_once()
        other=DensityStore(Path(self.temp.name)/'swim_tfms',source_type='swim_tfms')
        self.assertEqual(other.query()['cells'],[]);other.close()
        self.assertEqual(bridge.density_store.query()['cells'],[])

    def test_tfms_skips_coverage_worker_and_loading(self):
        bridge.CFG['source']='swim_tfms'
        with patch.object(bridge,'load_coverage') as load,patch.object(bridge,'refresh_home_marker') as home,patch.object(bridge,'flush_coverage') as flush:
            bridge.coverage_updater()
            load.assert_not_called();home.assert_not_called();flush.assert_not_called()
        for source in ('swim_tfms','sbs_30003','flights_js','aircraft_json'):
            bridge.CFG['source']=source
            with patch.object(bridge,'DensityStore',return_value=bridge.density_store),patch.object(bridge.atexit,'register'),patch.object(bridge.signal,'signal'),patch.object(bridge.threading,'Thread') as thread,patch.object(bridge,'refresh_tracker_enrichment'),patch.object(bridge,'ThreadingHTTPServer'),patch('builtins.print'):
                bridge.main()
                targets=[call.kwargs['target'] for call in thread.call_args_list]
                self.assertEqual(bridge.coverage_updater in targets,source!='swim_tfms')
                self.assertIn(bridge.density_maintenance,targets)
                self.assertIn(bridge.home_marker_updater,targets)
                if source=='swim_tfms':self.assertIn(bridge.swim_publisher,targets)

    def test_http_routes_restore_and_errors(self):
        bridge.collect_density([self.ac],time.time())
        code,query=self.request('/traffic-density');self.assertEqual(code,200)
        self.assertEqual(query['cells'][0]['observation_count'],1)
        code,geo=self.request('/traffic-density.geojson?zoom=15&bbox=-78,41,-76,43')
        self.assertEqual(code,200);self.assertEqual(geo['features'][0]['geometry']['type'],'Polygon')
        code,backup=self.request('/traffic-density/export');self.assertEqual(code,200)
        code,result=self.request('/traffic-density/import',backup);self.assertEqual(code,200)
        self.assertEqual(result['retained'],1)
        for path in ('/traffic-density?zoom=19','/traffic-density?start=bad','/traffic-density?bbox=nan,0,1,1','/traffic-density/export?month=bad'):
            self.assertEqual(self.request(path)[0],400)
        self.assertEqual(self.request('/traffic-density/import',{})[0],400)
        self.assertEqual(self.request('/traffic-density/status')[1]['base_zoom'],17)
        code,page=self.request('/status-page');self.assertEqual(code,200)
        self.assertIn('Restore density JSON',page)
        self.assertIn('traffic-density/export',page)
        code,page=self.request('/');self.assertEqual(code,200)
        self.assertIn('id="density-toggle" type="checkbox"',page)
        bridge.density_store.close();bridge.density_store=None
        self.assertEqual(self.request('/traffic-density')[0],503)
        bridge.density_store=DensityStore(self.temp.name,source_type=bridge.CFG["source"])

    def test_source_titles_range_controls_and_export_filenames(self):
        for source,prefix,label in (('sbs_30003','sbs','SBS'),('flights_js','fr24','FR24 HTTP'),('aircraft_json','d1090','ADSB JSON'),('swim_tfms','faa','FAA TFMS')):
            bridge.CFG['source']=source
            code,page=self.request('/')
            self.assertEqual(code,200)
            self.assertIn('<title>'+label+' → dump1090</title>',page)
            self.assertIn('id="range-toggle"',page)
            code,page=self.request('/status-page')
            self.assertIn(prefix+'-traffic-density.json',page)
            self.assertIn('body:f',page)
            self.assertEqual('id="range-backup"' in page,source!='swim_tfms')
            code,config=self.request('/map-config')
            self.assertEqual(config['coverage_outline_enabled'],source!='swim_tfms')
            with urlopen(self.base+'/traffic-density/export') as response:
                self.assertEqual(response.headers['Content-Disposition'],'attachment; filename="'+prefix+'-traffic-density.json"')
                response.read()
            if source=='swim_tfms':
                for path in ('/range-coverage','/range-coverage-baseline','/range-coverage.geojson'):
                    self.assertEqual(self.request(path)[0],404)
                self.assertEqual(self.request('/range-coverage/import',{})[0],404)

    def test_every_source_collects_one_snapshot_per_publication(self):
        sources=('flights_js','aircraft_json','sbs_30003','swim_tfms')
        for source in sources:
            bridge.CFG['source']=source
            with patch.object(bridge,'collect_density') as collect:
                if source=='flights_js':
                    with patch.object(bridge,'fetch_data',return_value='stub'),patch.object(bridge,'parse_jsonp',return_value={}),patch.object(bridge,'transform',return_value={'aircraft':[self.ac]}),patch.object(bridge.time,'sleep',side_effect=StopCycle):
                        with self.assertRaises(StopCycle):bridge.flights_js_updater()
                elif source=='aircraft_json':
                    from io import BytesIO
                    bridge.CFG['aircraft_json_url']='http://localhost/aircraft.json'
                    with patch.object(bridge,'urlopen',return_value=BytesIO(json.dumps({'aircraft':[self.ac],'messages':900000}).encode())),patch.object(bridge.time,'sleep',side_effect=StopCycle):
                        with self.assertRaises(StopCycle):bridge.aircraft_json_updater()
                elif source=='sbs_30003':
                    bridge.sbs_aircraft={'abc123':{**self.ac,'last_seen':time.time(),'position_seen':time.time()}}
                    with patch.object(bridge.time,'sleep',side_effect=[None,StopCycle]):
                        with self.assertRaises(StopCycle):bridge.sbs_publisher()
                else:
                    bridge.swim_aircraft={'abc123':{**self.ac,'_last_seen':time.time()}}
                    with patch.object(bridge.time,'sleep',side_effect=StopCycle):
                        with self.assertRaises(StopCycle):bridge.swim_publisher()
                self.assertEqual(collect.call_count,1,source)
                self.assertEqual(collect.call_args.args[0][0]['hex'],'abc123')

if __name__=='__main__':unittest.main()
