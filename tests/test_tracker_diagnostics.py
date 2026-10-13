"""Enrichment instance selection, partial failure and sanitized diagnostics."""
import unittest
from unittest.mock import patch
from urllib.error import HTTPError
import test_density_bridge as fixture
from bridge_config import validate_options
bridge=fixture.bridge

class TrackerTests(unittest.TestCase):
    def setUp(self):
        self.saved=dict(bridge.CFG)
        self.cache=(bridge.tracker_enrichment,bridge.tracker_enrichment_last_attempt,bridge.tracker_ever_detected,bridge.tracker_available_logged,bridge.tracker_diagnostic_last_log)
        bridge.CFG.update(enrichment_source='adsb_tracker',tracker_aircraft_entity='sensor.adsb_all_aircraft_2',tracker_closest_entity='sensor.adsb_closest_aircraft_2',tracker_military_entity='sensor.adsb_military_aircraft_details_2',destination_airport='BOS')
    def tearDown(self):
        bridge.CFG.clear();bridge.CFG.update(self.saved)
        bridge.tracker_enrichment,bridge.tracker_enrichment_last_attempt,bridge.tracker_ever_detected,bridge.tracker_available_logged,bridge.tracker_diagnostic_last_log=self.cache
    def test_optional_errors_do_not_block_routes(self):
        def attrs(entity):
            if entity=='sensor.adsb_all_aircraft_2':
                return {'total_aircraft':1,'aircraft_1':{'hex':'ABC123','route_destination':'BOS','tail':'N123'}}
            raise HTTPError('http://private/?password=secret',404,'missing',{},None)
        with patch.object(bridge,'_entity_attributes',side_effect=attrs),patch('builtins.print'):
            result=bridge.refresh_tracker_enrichment(force=True)
        self.assertTrue(result['available'])
        self.assertEqual(result['destination_hexes'],['abc123'])
        self.assertEqual(len(result['optional_sensor_errors']),2)
        self.assertNotIn('secret',str(result))
    def test_aggregate_failure_is_sanitized(self):
        with patch.object(bridge,'_entity_attributes',side_effect=HTTPError('http://private/?password=secret',503,'secret',{},None)),patch('builtins.print') as log:
            bridge.tracker_diagnostic_last_log=0
            result=bridge.refresh_tracker_enrichment(force=True)
        self.assertFalse(result['available'])
        self.assertEqual(result['diagnostic']['http_status'],503)
        self.assertEqual(result['entities']['tracker_aircraft_entity'],'sensor.adsb_all_aircraft_2')
        self.assertNotIn('secret',str(result)+str(log.call_args_list))
    def test_missing_attribute_reason(self):
        with patch.object(bridge,'_entity_attributes',return_value={}),patch('builtins.print'):
            result=bridge.refresh_tracker_enrichment(force=True)
        self.assertEqual(result['diagnostic']['reason'],'aggregate_attributes_missing')
    def test_entity_options_and_validation(self):
        cfg=validate_options({'source':'sbs_30003','receiver_host':'receiver','tracker_aircraft_entity':'sensor.adsb_all_aircraft_2'})
        self.assertEqual(cfg['tracker_aircraft_entity'],'sensor.adsb_all_aircraft_2')
        self.assertEqual(cfg['tracker_closest_entity'],'sensor.adsb_closest_aircraft')
        for bad in ('sensor.x/../../secret','light.test','http://private'):
            with self.assertRaises(ValueError):validate_options({'receiver_host':'receiver','tracker_aircraft_entity':bad})
