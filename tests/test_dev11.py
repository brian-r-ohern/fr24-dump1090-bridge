import sys,unittest
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'fr24-dump1090'))
from motion_state import MotionEngine
class ReportedSpeedTests(unittest.TestCase):
    def run_track(self,source,reported):
        clock=[1791800000.0];engine=MotionEngine(source,clock=lambda:clock[0]);lon=-77
        for i in range(13):
            clock[0]=1791800000+i*12
            lon+=.025 if i%2 else .01
            ac={'hex':'x','lat':42,'lon':lon,'alt_baro':29000}
            if reported is not None:ac['gs']=reported+i*3 if reported==300 else reported
            engine.observe([ac],clock[0],clock[0],{'x':{'position_time':clock[0],'gs_time':clock[0],'alt_baro_time':clock[0]}})
        return engine,clock
    def test_reported_constant_over_noisy_positions_and_unchanged_adsb(self):
        engine,clock=self.run_track('swim_sfdps',250)
        state=engine.snapshot()['aircraft']['x']
        self.assertIn('stable_speed',[p['name'] for p in state['primitives']])
        self.assertEqual(state['speed_basis'],'reported_ground_speed')
        self.assertGreater(state['speed_diagnostics']['derived_speed_range_knots'],100)
        self.assertEqual(state['speed_diagnostics']['speed_range_knots'],0)
        adsb,_=self.run_track('sbs_30003',250)
        self.assertNotIn('stable_speed',[p['name'] for p in adsb.snapshot()['aircraft']['x']['primitives']])
    def test_reported_trend_and_missing_value_fallback_end_events(self):
        trend,clock=self.run_track('swim_sfdps',300)
        self.assertIn('accelerating',[p['name'] for p in trend.snapshot()['aircraft']['x']['primitives']])
        engine,clock=self.run_track('swim_sfdps',250);clock[0]+=12
        engine.observe([{'hex':'x','lat':42,'lon':-76.7,'alt_baro':29000,'gs':250}],clock[0],clock[0],{'x':{'position_time':clock[0],'gs_time':clock[0]-60,'alt_baro_time':clock[0]}})
        state=engine.snapshot(include_events=True)['aircraft']['x']
        self.assertEqual(state['speed_basis'],'position_derived_ground_speed')
        self.assertTrue(any(p['ended_reason']=='speed_basis_changed' for p in state['completed_events']))
        self.assertIsNone(state['speed_diagnostics']['reported_speed_knots'])
    def test_restored_reported_speed_does_not_mix_histories(self):
        engine,clock=self.run_track('swim_sfdps',None);clock[0]+=12
        engine.observe([{'hex':'x','lat':42,'lon':-76.7,'gs':250}],clock[0],clock[0],{'x':{'position_time':clock[0],'gs_time':clock[0]}})
        diagnostic=engine.snapshot()['aircraft']['x']['speed_diagnostics']
        self.assertEqual(diagnostic['speed_basis'],'reported_ground_speed')
        self.assertEqual(diagnostic['usable_speed_samples'],1)
        self.assertIn('too_few_usable_speed_samples',diagnostic['blockers'])
