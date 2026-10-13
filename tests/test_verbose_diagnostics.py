import contextlib
import io
import json
from pathlib import Path
import sys
import tempfile
import unittest
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'fr24-dump1090'))
from motion_state import MotionEngine
from traffic_density import DensityStore
from bridge_config import validate_options
from bridge_settings import checked_options
NOW=1700000000
class VerboseTests(unittest.TestCase):
    def test_rejection_reasons_match_invalid_without_changing_admission(self):
        engine=MotionEngine('sbs_30003',clock=lambda:NOW)
        good={'hex':'abc123','lat':42,'lon':-77}
        invalid=[{'hex':'abc123'},dict(good,lat='bad'),dict(good,lon=181),good,good]
        times=[None,None,None,0,NOW+6]
        for ac,t in zip(invalid,times):engine.observe([ac],NOW,NOW,{'abc123':{'position_time':t}})
        s=engine.status()
        self.assertEqual(s['counters']['invalid'],5)
        self.assertEqual(sum(s['rejection_reasons'].values()),5)
        self.assertEqual(set(v for k,v in s['rejection_reasons'].items() if k!='missing_report_time'),{1})
        first=engine.diagnostic_summary();self.assertEqual(first['counters_delta']['invalid'],5)
        second=engine.diagnostic_summary();self.assertEqual(second['counters_delta']['invalid'],0)
        self.assertNotIn('abc123',json.dumps(first))
        engine.observe([good],NOW,NOW)
        self.assertEqual(engine.status()['counters']['accepted'],1)
    def test_density_timing_and_opt_in_logs_preserve_results(self):
        with tempfile.TemporaryDirectory() as folder:
            store=DensityStore(folder,clock=lambda:NOW,source_type='sbs_30003')
            try:
                store.observe([{'hex':'abc123','lat':42,'lon':-77,'alt_baro':10000}],NOW,'sbs_30003')
                output=io.StringIO()
                with contextlib.redirect_stdout(output):normal=store.geojson(zoom=11,max_cells=100)
                self.assertNotIn('[DEBUG]',output.getvalue())
                store.verbose_logging=True
                output=io.StringIO()
                with contextlib.redirect_stdout(output):verbose=store.geojson(zoom=11,max_cells=100)
                self.assertEqual(normal['features'],verbose['features'])
                self.assertTrue(verbose['diagnostics']['cached'])
                self.assertEqual(verbose['diagnostics']['sql_seconds'],0)
                self.assertIn('[DEBUG] Density diagnostics',output.getvalue())
                self.assertIn('[DEBUG] Density geometry',output.getvalue())
                for field in ('preparation_seconds','sql_seconds','aggregation_seconds','geometry_seconds','geojson_seconds'):self.assertGreaterEqual(verbose['diagnostics'][field],0)
            finally:store.close()
    def test_configuration_and_settings_snapshot_include_toggle(self):
        cfg={'source':'sbs_30003','receiver_host':'localhost','verbose_logging':True}
        self.assertTrue(validate_options(cfg)['verbose_logging'])
        self.assertTrue(checked_options(cfg)['verbose_logging'])
        self.assertFalse(validate_options({'receiver_host':'localhost'})['verbose_logging'])
        with self.assertRaises(ValueError):validate_options(dict(cfg,verbose_logging='true'))
