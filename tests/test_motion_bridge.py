"""Exercise real HTTP and independent publisher hooks without changing feeds."""
import json
import time
import unittest
from unittest.mock import patch
import test_density_bridge as fixture
from motion_state import MotionEngine
bridge=fixture.bridge


class MotionBridgeTests(unittest.TestCase):
    request=fixture.DensityBridgeTests.request

    def setUp(self):
        fixture.DensityBridgeTests.setUp(self)
        self.saved=bridge.motion_engine
        bridge.CFG['source']='sbs_30003'
        bridge.motion_engine=MotionEngine('sbs_30003')

    def tearDown(self):
        bridge.motion_engine=self.saved
        fixture.DensityBridgeTests.tearDown(self)

    def test_routes_limits_privacy_and_no_consumer_credit(self):
        now=time.time()
        bridge.collect_snapshot([self.ac],now,now,{'abc123':{'position_time':now}})
        with patch.object(bridge.feed_consumers,'record') as consumers:
            status,state=self.request('/motion?hex=ABC123')
            self.assertEqual(status,200)
            self.assertEqual(state['aircraft']['abc123']['quality'],'warming_up')
            self.assertNotIn('lat',state['aircraft']['abc123'])
            self.assertNotIn('lon',state['aircraft']['abc123'])
            self.assertEqual(self.request('/motion?hex=bad!')[0],400)
            self.assertEqual(self.request('/motion?hex='+','.join(['abc123']*257))[0],400)
            self.assertEqual(self.request('/motion/status')[1]['retained_samples'],1)
            consumers.assert_not_called()
        s=self.request('/status')[1]
        self.assertTrue(s['motion']['available'])
        self.assertEqual(s['motion']['supported_sources'],['sbs_30003','aircraft_json','swim_sfdps'])
        self.assertIn('Motion analytics',self.request('/status-page')[1])

    def test_disabled_sources_continue_density_and_eta(self):
        for source,reason in [('swim_tfms','selected_source_excluded'),('flights_js','position_precision_excluded')]:
            bridge.CFG['source']=source
            with patch.object(bridge,'collect_density') as density:
                bridge.collect_snapshot([self.ac],time.time())
                density.assert_called_once()
            s=self.request('/motion/status')[1]
            self.assertFalse(s['available']);self.assertEqual(s['reason'],reason)
            self.assertEqual(s['retained_samples'],0)
            if source == 'swim_tfms':self.assertEqual(self.request('/motion')[0],403)
            else:self.assertEqual(self.request('/motion')[1]['aircraft'],{})
            self.assertEqual(self.request('/airport-lookup?codes=KSYR')[0],200)

    def test_density_unavailable_and_motion_failure_are_isolated(self):
        original=bridge.density_store;bridge.density_store=None
        try:
            bridge.collect_snapshot([self.ac],time.time())
            self.assertEqual(bridge.motion_engine.status()['retained_samples'],1)
        finally:bridge.density_store=original
        with patch.object(bridge.motion_engine,'observe',side_effect=ValueError('bad')),patch.object(bridge,'collect_density') as density,patch('builtins.print'):
            bridge.collect_snapshot([self.ac],time.time())
            density.assert_called_once()
            self.assertEqual(bridge.motion_engine.last_error,'ValueError')

    def test_sbs_private_times_and_feed_unchanged(self):
        now=time.time()
        old=bridge.sbs_aircraft
        try:
            bridge.sbs_aircraft={}
            bridge.apply_sbs_update({**self.ac,'position_update':True},now)
            metadata=bridge.sbs_aircraft['abc123']['_motion_field_times']
            self.assertEqual(metadata['alt_baro_time'],now)
            with patch.object(bridge,'collect_snapshot') as collect,patch.object(bridge.time,'sleep',side_effect=[None,fixture.StopCycle]):
                with self.assertRaises(fixture.StopCycle):bridge.sbs_publisher()
            args=collect.call_args.args
            self.assertEqual(args[3]['abc123']['position_time'],now)
            self.assertEqual(args[3]['abc123']['alt_baro_time'],now)
            self.assertNotIn('_motion_field_times',args[0][0])
            self.assertNotIn('motion',args[0][0])
        finally:bridge.sbs_aircraft=old

    def test_every_publisher_reaches_independent_motion_hook(self):
        # Existing one-cycle fixture asserts unchanged density calls; wrap the
        # common hook to verify source analytics is also reached for every mode.
        with patch.object(bridge,'collect_snapshot',wraps=bridge.collect_snapshot) as collected:
            fixture.DensityBridgeTests.test_every_source_collects_one_snapshot_per_publication(self)
        self.assertEqual(collected.call_count,4)


if __name__=='__main__':unittest.main()
