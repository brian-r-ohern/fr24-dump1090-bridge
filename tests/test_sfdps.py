"""Synthetic FIXM fixtures only: captured FAA records must not ship in releases."""
import json
import re
import tempfile
import threading
import time
import unittest
from pathlib import Path
from unittest.mock import patch
from urllib.error import HTTPError
from urllib.request import Request, urlopen
from test_density_bridge import bridge
from swim_sfdps import parse_sfdps_tracks
from bridge_config import validate_options
from bridge_settings import checked_options


def fixture(position='40 -75', timestamp='2026-10-10T20:00:00Z', unit='FEET', crs='urn:ogc:def:crs:EPSG::4326', report='SURVEILLANCE'):
    return f'''<n:MessageCollection xmlns:n="http://www.faa.aero/nas/3.0"><message><flight source="TH">
      <gufi>synthetic-occurrence-1</gufi><flightIdentification aircraftIdentification="TEST123"/>
      <departure departurePoint="KAAA"/><arrival arrivalPoint="KBBB"/>
      <enRoute><position positionTime="{timestamp}" reportSource="{report}">
        <actualSpeed><surveillance uom="KNOTS">210</surveillance></actualSpeed>
        <altitude uom="{unit}">12000</altitude>
        <position><location srsName="{crs}"><pos>{position}</pos></location></position>
        <targetPosition srsName="{crs}"><pos>0 0</pos></targetPosition>
        <targetAltitude uom="FEET">99000</targetAltitude>
        <trackVelocity><x uom="KNOTS">100</x><y uom="KNOTS">100</y></trackVelocity>
      </position></enRoute><supplementalData><nameValue name="ADSB_02M_52B" value="-ABC123"/></supplementalData>
      <assignedAltitude><simple uom="FEET">40000</simple></assignedAltitude>
    </flight></message></n:MessageCollection>'''


class SfdpsParserTests(unittest.TestCase):
    def test_observed_scope_units_identity_and_no_axis_assumption(self):
        diagnostics={}; tracks,count=parse_sfdps_tracks(fixture(),diagnostics)
        self.assertEqual(count,1); self.assertEqual(len(tracks),1)
        t=tracks[0]; self.assertEqual((t['lat'],t['lon']),(40,-75));self.assertEqual(t['alt_baro'],12000)
        self.assertEqual(t['gs'],210); self.assertEqual(t['icao_address'],'abc123')
        self.assertEqual(t['_tfms_gufi'],'synthetic-occurrence-1')
        self.assertEqual(t['route_destination'],'KBBB'); self.assertNotIn('track',t)
        self.assertEqual(diagnostics['positioned_tracks'],1)

    def test_reject_invalid_current_positions_times_crs_and_report(self):
        for kwargs in ({'position':'nan -75'},{'position':'91 -75'},{'position':'40 181'},
                       {'position':'40'}, {'timestamp':'bad'}, {'timestamp':'2026-10-10T20:00:00'},
                       {'crs':'EPSG:3857'},{'report':'PREDICTED'}):
            self.assertEqual(parse_sfdps_tracks(fixture(**kwargs))[0],[],kwargs)
        # No fallback from absent observation to target / route / assigned fields.
        s=fixture().replace('<pos>40 -75</pos>','')
        self.assertEqual(parse_sfdps_tracks(s)[0],[])

    def test_unknown_units_omitted_missing_gufi_not_callsign_fallback(self):
        t=parse_sfdps_tracks(fixture(unit='FL'))[0][0];self.assertNotIn('alt_baro',t)
        self.assertEqual(parse_sfdps_tracks(fixture().replace('<gufi>synthetic-occurrence-1</gufi>',''))[0],[])

    def test_namespaces_multiple_flights_and_malformed_payload(self):
        s=fixture().replace('<flight ','<n:flight ').replace('</flight>','</n:flight>')
        self.assertEqual(len(parse_sfdps_tracks(s)[0]),1)
        with self.assertRaises(Exception):parse_sfdps_tracks('<broken>')

    def test_configuration_recovery_and_source_controls_product(self):
        opts={'source':'swim_sfdps','swim_host':'host','swim_vpn':'vpn',
              'swim_username':'user','swim_password':'secret','swim_queue':'queue'}
        cfg=validate_options(opts);self.assertEqual(cfg['swim_product'],'sfdps')
        self.assertEqual(checked_options(opts)['source'],'swim_sfdps')
        with self.assertRaises(ValueError):validate_options({**opts,'swim_queue':''})


class SfdpsIsolationTests(unittest.TestCase):
    def setUp(self):
        self.cfg=dict(bridge.CFG);self.original=dict(bridge.swim_aircraft);self.data=bridge.latest_data
        bridge.CFG.update(source='swim_sfdps',swim_product='sfdps',swim_radius_nm=250,swim_aircraft_timeout=120)
        bridge.swim_aircraft.clear();bridge.latest_data={'now':1,'aircraft':[{'hex':'~synthetic','flight':'TEST123','lat':40,'lon':-75}]}
        self.server=bridge.ThreadingHTTPServer(('127.0.0.1',0),bridge.Handler)
        self.thread=threading.Thread(target=self.server.serve_forever,daemon=True);self.thread.start()
        self.base='http://127.0.0.1:'+str(self.server.server_port)

    def tearDown(self):
        self.server.shutdown();self.server.server_close();self.thread.join()
        bridge.CFG.clear();bridge.CFG.update(self.cfg);bridge.swim_aircraft.clear();bridge.swim_aircraft.update(self.original);bridge.latest_data=self.data

    def request(self,path,post=False):
        try:r=urlopen(Request(self.base+path,data=b'{}' if post else None),timeout=5)
        except HTTPError as exc:r=exc
        with r:return r.status,r.read().decode()

    def test_feed_export_history_routes_denied_and_local_map_available(self):
        for source in ('swim_sfdps','swim_tfms'):
            bridge.CFG['source']=source
            for route in ('/aircraft.json','/data/aircraft.json','/data/aircraft.json?client_id=test','/track-history?callsign=test'):
                code,body=self.request(route);self.assertEqual(code,403);self.assertNotIn('TEST123',body)
            code,page=self.request('/');self.assertEqual(code,200);self.assertIn('faa-map-state',page)
            self.assertIn('TEST123',page);self.assertIn('local view',page)
        bridge.CFG['source']='sbs_30003';self.assertEqual(self.request('/data/aircraft.json')[0],200)

    def test_sfdps_density_enabled_range_and_feed_outputs_remain_disabled(self):
        for route in ('/traffic-density','/range-coverage','/range-coverage.geojson','/motion'):
            self.assertIn(self.request(route)[0],(403,404))
        with tempfile.TemporaryDirectory() as temp, patch.dict('os.environ',{'FR24_DENSITY_PATH':temp+'/density'}):
            store=bridge.open_density_store()
            self.assertEqual(store.source_type,'swim_sfdps')
            self.assertTrue(Path(temp+'/density/swim_sfdps').exists())
            with patch.object(bridge,'density_store',store):
                self.assertEqual(self.request('/traffic-density/status')[0],200)
                status=json.loads(self.request('/traffic-density/cache-status?zoom=11&bbox=-78,41,-76,43')[1])
                self.assertGreater(status['to_build'],0)
                self.assertNotIn('features',status)
                with patch.object(bridge,'motion_engine',bridge.MotionEngine('swim_sfdps')):
                    bridge.collect_snapshot([{'hex':'sfdps-key','lat':42,'lon':-77,'alt_baro':5000}],time.time(),metadata={'sfdps-key':{'position_time':time.time()}})
                    self.assertEqual(store.query()['cells'][0]['observation_count'],1)
                    self.assertTrue(bridge.get_motion_engine().status()['available'])
                    code,page=self.request('/?density_view=1&zoom=11&bbox=-78,41,-76,43')
                    self.assertEqual(code,200);self.assertIn('faa-density-state',page);self.assertIn('faa-motion-state',page)
        code,page=self.request('/status-page');self.assertEqual(code,200)
        self.assertIn('id="density-backup"',page);self.assertIn('id="density-envelope-backup"',page)

    def test_publisher_passes_report_epoch_for_motion(self):
        epoch=time.time()-12
        from datetime import datetime,timezone
        bridge.swim_aircraft.clear()
        bridge.swim_aircraft['sfdps-track']={'hex':'sfdps-track','lat':42,'lon':-77,'position_time':datetime.fromtimestamp(epoch,timezone.utc).isoformat(),'_last_seen':time.time()}
        with patch.object(bridge,'collect_snapshot') as collector,patch.object(bridge.time,'sleep',side_effect=RuntimeError('stop loop')):
            with self.assertRaisesRegex(RuntimeError,'stop loop'):bridge.swim_publisher()
        aircraft,received,source_now,metadata=collector.call_args.args
        self.assertAlmostEqual(metadata['sfdps-track']['position_time'],epoch,places=5)
        self.assertEqual(metadata['sfdps-track']['time_basis'],'sfdps_report_time')
        self.assertEqual(metadata['sfdps-track']['altitude_reference'],'sfdps_reported_altitude')
        self.assertGreaterEqual(aircraft[0]['seen_pos'],12)

    def test_missing_home_gate_stale_future_duplicate_and_course(self):
        now=time.time()
        def payload(dt=0,pos='40 -75'):
            from datetime import datetime,timezone
            return fixture(position=pos,timestamp=datetime.fromtimestamp(now+dt,timezone.utc).isoformat())
        with patch.object(bridge,'_swim_home',return_value=None):bridge._handle_swim_payload(payload())
        self.assertEqual(bridge.swim_aircraft,{})
        with patch.object(bridge,'_swim_home',return_value=(40,-75)):
            bridge._handle_swim_payload(payload(-1000));bridge._handle_swim_payload(payload(60));self.assertFalse(bridge.swim_aircraft)
            bridge._handle_swim_payload(payload(-20));self.assertEqual(len(bridge.swim_aircraft),1)
            key=next(iter(bridge.swim_aircraft));first=bridge.swim_aircraft[key]
            self.assertEqual(len(key),17);self.assertNotIn('track',first)
            bridge._handle_swim_payload(payload(-30));self.assertIs(bridge.swim_aircraft[key],first)
            bridge._handle_swim_payload(payload(0,'40 -74.99'))
            self.assertAlmostEqual(bridge.swim_aircraft[key]['track'],90,delta=1)
        with patch.object(bridge,'_swim_home',return_value=(0,0)):bridge._handle_swim_payload(payload())
        self.assertEqual(len(bridge.swim_aircraft),1)

    def test_density_tile_view_is_not_an_faa_data_output(self):
        for source in ('swim_tfms','swim_sfdps'):
            bridge.CFG['source']=source
            code,_=self.request('/traffic-density/view?zoom=11&bbox=-78,41,-76,43')
            self.assertEqual(code,403)

    def test_map_script_escaping_and_marker_dimensions(self):
        bridge.latest_data['aircraft'][0]['flight']='</script><script>bad</script>'
        code,page=self.request('/');self.assertEqual(code,200)
        match=re.search(r'<script id="faa-map-state" type="application/json">(.*?)</script>',page)
        data=json.loads(match.group(1));self.assertEqual(data['aircraft'][0]['flight'],'</script><script>bad</script>')
        self.assertNotIn('</script>',match.group(1))
        self.assertIn('iconSize:[size,size],iconAnchor:[size/2,size/2]',page)
        self.assertIn('.plane svg{display:block;width:100%;height:100%',page)

    def test_bounded_view_and_status_without_positions_or_gufi(self):
        now=time.time()
        bridge.swim_aircraft.update({str(i):{'_last_seen':now-100+i/100,'position_time':'2026-10-10T00:00:00Z'} for i in range(4096)})
        from datetime import datetime,timezone
        with patch.object(bridge,'_swim_home',return_value=(40,-75)):
            bridge._handle_swim_payload(fixture(timestamp=datetime.fromtimestamp(now,timezone.utc).isoformat()))
        self.assertEqual(len(bridge.swim_aircraft),4096);self.assertNotIn('0',bridge.swim_aircraft)
        code,body=self.request('/status');self.assertEqual(code,200)
        status=json.loads(body);self.assertEqual(status['source'],'swim_sfdps')
        self.assertFalse(status['bridge_enabled']);self.assertTrue(status['density_enabled'])
        self.assertNotIn('synthetic-occurrence-1',body);self.assertNotIn('"lat"',body)
        config=json.loads(self.request('/map-config')[1]);self.assertFalse(config['coverage_outline_enabled'])
        self.assertFalse(config['track_history_available']);self.assertEqual(config['enrichment_source'],'none')
