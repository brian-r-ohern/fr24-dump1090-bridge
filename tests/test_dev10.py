import sys,tempfile,unittest,math
from pathlib import Path
from unittest.mock import patch
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'fr24-dump1090'))
from motion_state import MotionEngine
from traffic_density import DensityStore
from density_tiles import CacheNotReady

class SpeedDiagnosticsTests(unittest.TestCase):
    def trajectory(self,source,variable=False):
        now=[1791800000.0];engine=MotionEngine(source,clock=lambda:now[0]);lon=-77
        for i in range(13):
            now[0]=1791800000+i*12
            if i:lon+=(400 if variable and i%2 else 200)*.514444*12/(6371000*math.cos(math.radians(42)))*180/math.pi
            ac={'hex':'test-track','lat':42,'lon':lon,'alt_baro':29000,'gs':220}
            engine.observe([ac],now[0],now[0],{'test-track':{'position_time':now[0],'gs_time':now[0],'alt_baro_time':now[0]}})
        return engine
    def test_reported_values_do_not_drive_stable_speed(self):
        for source in ('sbs_30003','aircraft_json','swim_sfdps'):
            engine=self.trajectory(source)
            state=engine.snapshot()['aircraft']['test-track'];diagnostics=state['speed_diagnostics']
            self.assertTrue(diagnostics['stable_speed']);self.assertEqual(diagnostics['blockers'],[])
            self.assertAlmostEqual(state['metrics']['ground_speed_knots'],200,delta=.1)
            self.assertEqual(diagnostics['reported_speed_knots'],220)
            self.assertAlmostEqual(diagnostics['latest_leg_derived_minus_latest_reported_knots'],-20,delta=.1)
            self.assertEqual(diagnostics['report_intervals_seconds']['median'],12)
            self.assertEqual(diagnostics['reported_speed_semantics'],'reported_ground_speed')
            summary=engine.diagnostic_summary()
            self.assertNotIn('test-track',str(summary));self.assertNotIn('lat',summary['speed_analysis'])
            self.assertEqual(summary['speed_analysis']['reported_speed_knots']['count'],1)
    def test_variation_blockers_match_failed_rule(self):
        engine=self.trajectory('sbs_30003',True)
        diagnostics=engine.snapshot()['aircraft']['test-track']['speed_diagnostics']
        self.assertFalse(diagnostics['stable_speed'])
        self.assertIn('excessive_speed_variation',diagnostics['blockers'])
        self.assertIn('excessive_fit_residual',diagnostics['blockers'])
        self.assertGreater(diagnostics['speed_range_knots'],190)
        self.assertEqual(engine.diagnostic_summary()['speed_analysis']['stable_speed_blockers']['excessive_speed_variation'],1)
    def test_stale_report_not_compared_and_warmup_explained(self):
        engine=MotionEngine('sbs_30003',clock=lambda:1791800000)
        engine.observe([{'hex':'x','lat':42,'lon':-77,'gs':200}],1791800000,1791800000,{'x':{'gs_time':1791799900}})
        diagnostic=engine.snapshot()['aircraft']['x']['speed_diagnostics']
        self.assertIsNone(diagnostic['reported_speed_knots'])
        self.assertIsNone(diagnostic['latest_leg_derived_minus_latest_reported_knots'])
        self.assertIn('too_few_position_samples',diagnostic['blockers'])

class AutomaticCacheTests(unittest.TestCase):
    def test_cache_only_never_builds_on_missing_or_expired_view(self):
        with tempfile.TemporaryDirectory() as folder:
            now=[1791800000.0];store=DensityStore(folder,source_type='sbs_30003',clock=lambda:now[0])
            options={'zoom':11,'bbox':[-78,41,-76,43]}
            with patch.object(store,'query',side_effect=AssertionError('automatic load must not run SQL')):
                with self.assertRaises(CacheNotReady):store.view(**options,cached_only=True)
            store.view(**options)
            with patch.object(store,'query',side_effect=AssertionError('automatic load must not run SQL')):
                loaded=store.view(**options,cached_only=True)
                self.assertTrue(loaded['diagnostics']['cached'])
                self.assertEqual(loaded['diagnostics']['aggregated_rows_read'],0)
                now[0]+=7200
                with self.assertRaises(CacheNotReady):store.view(**options,cached_only=True)
            store.clear()
            with self.assertRaises(CacheNotReady):store.view(**options,cached_only=True)
    def test_uncacheable_and_force_conflict_fail_without_query(self):
        with tempfile.TemporaryDirectory() as folder:
            store=DensityStore(folder,source_type='sbs_30003')
            with patch.object(store,'geojson',side_effect=AssertionError('no fallback query')):
                with self.assertRaises(CacheNotReady):store.view(cached_only=True)
                with self.assertRaises(CacheNotReady):store.view(zoom=17,bbox=[-180,-90,180,90],cached_only=True)
                with self.assertRaises(ValueError):store.view(cached_only=True,bypass_cache=True)
