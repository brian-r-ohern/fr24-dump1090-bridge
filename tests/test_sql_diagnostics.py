import contextlib
import io
import tempfile
import unittest
from unittest.mock import patch
from pathlib import Path
import sys
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/"fr24-dump1090"))
from traffic_density import DensityStore
class SqlDiagnosticsTests(unittest.TestCase):
    def test_plan_work_and_bypass_preserve_data(self):
        now=1700000000
        with tempfile.TemporaryDirectory() as folder:
            store=DensityStore(folder,clock=lambda:now,source_type='sbs_30003')
            try:
                aircraft=[{'hex':str(i),'lat':42+i*.002,'lon':-77+i*.002,'alt_baro':10000} for i in range(50)]
                store.observe(aircraft,now,'sbs_30003');store.verbose_logging=True
                with contextlib.redirect_stdout(io.StringIO()):
                    first=store.query(zoom=11,max_cells=100)
                    cached=store.query(zoom=11,max_cells=100)
                    bypass=store.query(zoom=11,max_cells=100,bypass_cache=True)
                self.assertFalse(first['diagnostics']['cached'])
                self.assertTrue(cached['diagnostics']['cached'])
                self.assertFalse(bypass['diagnostics']['cached'])
                self.assertTrue(bypass['diagnostics']['cache_bypassed'])
                self.assertEqual(first['cells'],bypass['cells'])
                month=bypass['diagnostics']['monthly_queries'][0]
                self.assertTrue(month['query_plan'])
                self.assertNotIn('-77',str(month['query_plan']))
                self.assertGreater(month['database']['page_count'],0)
                self.assertGreaterEqual(month['vm_steps_approx'],0)
                self.assertGreaterEqual(month['execution_thread_cpu_seconds'],0)
                self.assertEqual(cached['diagnostics']['monthly_queries'],[])
                store.verbose_logging=False
                with contextlib.redirect_stdout(io.StringIO()):normal=store.query(zoom=11,bypass_cache=True)
                self.assertNotIn('query_plan',normal['diagnostics']['monthly_queries'][0])
            finally:store.close()

    def test_callback_removed_after_fetch_processing_exception(self):
        now=1700000000
        with tempfile.TemporaryDirectory() as folder:
            store=DensityStore(folder,clock=lambda:now,source_type='sbs_30003')
            try:
                store.observe([{'hex':'abc','lat':42,'lon':-77}],now,'sbs_30003')
                store.verbose_logging=True
                with patch('traffic_density.parent',side_effect=ValueError('synthetic')):
                    with self.assertRaises(ValueError):store.query(zoom=11)
                with contextlib.redirect_stdout(io.StringIO()):result=store.query(zoom=11)
                self.assertEqual(len(result['cells']),1)
            finally:store.close()
