"""Altitude filtering and approximate, cached 0.5-degree comparison envelopes."""
import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'fr24-dump1090'))
from traffic_density import DensityStore,cell_id,polygon
from density_archive import geojson_file
from density_envelopes import EnvelopeCache,CACHE_SECONDS
import test_density_bridge as bridge_tests
bridge=bridge_tests.bridge

NOW=1791309319.0

class DensityViewTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory()
        self.store=DensityStore(self.temp.name,clock=lambda:NOW,source_type='sbs_30003')
        ring=polygon(cell_id(41,-77));self.lon=(ring[0][0]+ring[1][0])/2
        self.home={'latitude':40,'longitude':self.lon}
        for index,(lat,alt) in enumerate(((41,700),(42,5000),(43,37000),(44,None))):
            self.store.observe([{'hex':str(index),'lat':lat,'lon':self.lon,'alt_baro':alt}],NOW)
        self.cache=EnvelopeCache(self.store,clock=lambda:NOW)

    def test_envelope_diagnostics_preserve_results_and_cache(self):
        from contextlib import redirect_stdout
        import io
        quiet = self.cache.get(self.home)
        self.cache.entries.clear()
        self.store.verbose_logging = True
        output = io.StringIO()
        with redirect_stdout(output):
            result = self.cache.get(self.home)
            cached = self.cache.get(self.home)
        self.assertEqual(quiet, result)
        self.assertTrue(cached['cached'])
        records = [json.loads(line.split('Envelope diagnostics ',1)[1]) for line in output.getvalue().splitlines()]
        stages = {record['stage'] for record in records}
        self.assertTrue({'snapshot_copy_completed', 'window_aggregation_completed', 'bearing_calculation_completed', 'generation_completed', 'cache_hit'} <= stages)
        self.assertEqual(len({record['job_id'] for record in records}), 2)

    def test_sql_aggregation_matches_row_path_across_months(self):
        from density_archive import window_cells
        from traffic_density import FIELDS
        self.store.flush(True)
        cell = cell_id(41,self.lon)
        # Shared cell in multiple months, mixed complete/legacy history and NULL altitudes.
        for month, day, complete, first, minimum, maximum in (
            ('2026-09','2026-09-30',1,1.0,None,None),
            ('2026-10','2026-10-01',0,None,400,900),
            ('2026-10','2026-10-02',1,3.0,600,1200)):
            db = self.store._db(month)
            db.execute('INSERT INTO daily VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)',
                       (cell,day,7,2,1,2,3,1,minimum,maximum,first,4.0,complete))
            db.commit()
        start,end='2026-09-30','2026-10-06'
        def rows(sql):
            with window_cells(self.store,start,end,sql_base_cells=sql) as (_,db,_):
                return [dict(row) for row in db.execute('SELECT * FROM daily ORDER BY cell')]
        self.assertEqual(rows(False),rows(True))
        with patch('density_envelopes.window_cells',
                   side_effect=lambda *args,**kwargs: window_cells(*args,**{**kwargs,'sql_base_cells':False})):
            expected=EnvelopeCache(self.store,clock=lambda:NOW).get(self.home,start,end)
        actual=EnvelopeCache(self.store,clock=lambda:NOW).get(self.home,start,end)
        self.assertEqual(actual,expected)
        self.assertEqual(sum(b['observation_count'] for b in actual['products']['all']['bins']),25)

    def test_saved_restart_age_force_and_failed_replacement(self):
        first=self.cache.get(self.home)
        restarted=EnvelopeCache(self.store,clock=lambda:NOW+43201)
        with patch('density_envelopes.window_cells',side_effect=AssertionError('load must not aggregate')):
            info=restarted.saved(self.home,status_only=True)
            self.assertTrue(info['available']);self.assertTrue(info['refresh_recommended'])
            loaded=restarted.saved(self.home)
            self.assertEqual(loaded['products'],first['products'])
            with self.assertRaises(AssertionError):restarted.get(self.home,force=True)
        self.assertEqual(restarted.saved(self.home)['products'],first['products'])
        self.assertFalse(restarted.saved({**self.home,'longitude':1},status_only=True)['available'])
        self.assertFalse(restarted.saved(self.home,status_only=True,start='2026-01-01')['available'])
        with patch('density_envelopes.os.replace',side_effect=OSError('disk failure')):
            with self.assertRaises(OSError):self.cache.get(self.home,force=True)
        self.assertEqual(restarted.saved(self.home)['products'],first['products'])
        with patch('density_envelopes.window_cells',side_effect=AssertionError('forced build')):
            with self.assertRaises(AssertionError):self.cache.get(self.home,force=True)
        self.store.restore(self.store.export())
        self.assertFalse(restarted.saved(self.home,status_only=True)['available'])
        self.cache.get(self.home,force=True)
        self.store.clear()
        self.assertFalse(restarted.saved(self.home,status_only=True)['available'])

    def test_saved_survives_store_reopen(self):
        expected=self.cache.get(self.home)
        self.store.close()
        self.store=DensityStore(self.temp.name,clock=lambda:NOW,source_type='sbs_30003')
        service=EnvelopeCache(self.store,clock=lambda:NOW+60)
        loaded=service.saved(self.home)
        self.assertEqual(loaded['products'],expected['products'])
        self.assertEqual(loaded['age_seconds'],60)

    def test_build_allows_retention_prune_before_snapshot(self):
        original=self.store.prune
        called=False
        def prune_once():
            nonlocal called
            original()
            if not called:
                self.store.restore_epoch+=1
                called=True
        with patch.object(self.store,'prune',side_effect=prune_once):
            built=self.cache.get(self.home,force=True)
        self.assertTrue(called)
        self.assertEqual(self.cache.saved(self.home)['products'],built['products'])

    def test_malformed_saved_result_is_unavailable(self):
        path=self.store.directory/'last-envelope.json'
        for value in ([],{'saved_schema':1,'source':'sbs_30003','home':self.home,'payload':[]}):
            path.write_text(json.dumps(value))
            self.assertFalse(self.cache.saved(self.home,status_only=True)['available'])
            with self.assertRaises(ValueError):self.cache.saved(self.home)

    def tearDown(self):
        self.store.close();self.temp.cleanup()

    def test_filter_combinations_unknown_and_unchanged_backup(self):
        backup=self.store.export()
        for bands,count in (('all',4),('low',1),('middle',1),('high',1),('low,high',2),('high,middle,low',3),('none',0)):
            result=self.store.query(bands=bands,zoom=0)
            self.assertEqual(sum(c['selected_observation_count'] for c in result['cells']),count)
            if count:
                self.assertEqual(result['cells'][0]['observation_count'],4)
                self.assertEqual(result['cells'][0]['altitude']['unknown'],1)
        self.assertEqual(self.store.export(),backup)
        for bands in ('unknown','low,all','low,low','LOW',''):
            with self.assertRaises(ValueError):self.store.query(bands=bands)

    def test_streamed_selected_geojson_matches_live_query(self):
        for bands in ('all','middle,high','none'):
            expected=self.store.geojson(bands=bands,zoom=14)
            with geojson_file(self.store,bands=bands,zoom=14) as path:
                self.assertEqual(json.loads(path.read_text()),expected)

    def test_four_products_use_same_window_and_center_bearing(self):
        payload=self.cache.get(self.home)
        self.assertEqual(payload['bin_degrees'],.5);self.assertEqual(payload['total_bins'],720)
        self.assertFalse(payload['authoritative'])
        self.assertEqual(payload['position_method'],'base_cell_center')
        bins={name:product['bins'][0] for name,product in payload['products'].items()}
        self.assertEqual(bins['all']['observation_count'],4)
        self.assertEqual(bins['all']['qualifying_cell_passage_count'],4)
        for name in ('low','middle','high'):
            self.assertEqual(bins[name]['observation_count'],1)
            self.assertEqual(bins[name]['bearing'],0)
        distances=[bins[b]['distance_nm'] for b in ('low','middle','high','all')]
        self.assertEqual(distances,sorted(distances));self.assertEqual(len(set(distances)),4)
        # An empty date window does not fall back to lifetime counts.
        empty=self.cache.get(self.home,'2026-10-05','2026-10-05')
        self.assertTrue(all(p['populated_bins']==0 for p in empty['products'].values()))

    def test_cache_copy_home_key_expiry_and_restore_invalidation(self):
        first=self.cache.get(self.home)
        first['products']['low']['bins'].clear()
        cached=self.cache.get(self.home)
        self.assertTrue(cached['cached']);self.assertEqual(len(cached['products']['low']['bins']),1)
        self.assertFalse(self.cache.get({**self.home,'longitude':self.lon+1})['cached'])
        self.store.restore(self.store.export())
        self.assertFalse(self.cache.get(self.home)['cached'])
        self.cache.clock=lambda:NOW+CACHE_SECONDS+1
        self.assertFalse(self.cache.get(self.home)['cached'])
        with self.assertRaises(ValueError):self.cache.get(None)
        with self.assertRaises(ValueError):self.cache.get({'latitude':91,'longitude':0})

    def test_combined_passages_are_explicitly_labeled(self):
        # Two altitude bands in a single cell share one stored passage counter.
        self.store.observe([{'hex':'new','lat':41,'lon':self.lon,'alt_baro':37000}],NOW+1)
        result=self.cache.get(self.home)
        low=result['products']['low']['bins'][0]
        self.assertEqual(low['observation_count'],1)
        self.assertEqual(low['qualifying_cell_passage_count'],2)
        self.assertIn('not altitude-specific',result['passage_count_basis'])

class DensityEnvelopeHttpTests(bridge_tests.DensityBridgeTests):
    # Reuse server lifecycle/helpers, not the inherited publisher test cases.
    test_every_source_collects_one_snapshot_per_publication=None
    test_http_routes_restore_and_errors=None
    test_source_titles_range_controls_and_export_filenames=None
    test_tfms_skips_coverage_worker_and_loading=None

    def test_saved_envelope_http_load_status_and_faa_denial(self):
        bridge.collect_density([self.ac],NOW)
        original=bridge.home_marker
        try:
            bridge.home_marker={'latitude':41,'longitude':-77}
            code,info=self.request('/traffic-density/envelopes?action=status')
            self.assertEqual(code,200);self.assertFalse(info['available'])
            self.assertEqual(self.request('/traffic-density/envelopes?action=load')[0],400)
            code,built=self.request('/traffic-density/envelopes?action=build')
            self.assertEqual(code,200)
            code,loaded=self.request('/traffic-density/envelopes?action=load')
            self.assertEqual(code,200);self.assertEqual(loaded['products'],built['products'])
            self.assertTrue(self.request('/traffic-density/envelopes?action=status')[1]['available'])
            bridge.CFG['source']='swim_sfdps'
            for action in ('status','load','build'):
                self.assertEqual(self.request('/traffic-density/envelopes?action='+action)[0],200)
        finally:
            bridge.home_marker=original;bridge.CFG['source']='sbs_30003'

    def test_envelope_routes_gap_geometry_and_tfms_label(self):
        bridge.collect_density([self.ac],NOW)
        original=bridge.home_marker
        try:
            bridge.home_marker={'latitude':41,'longitude':-77}
            code,payload=self.request('/traffic-density/envelopes?start=2026-10-06&end=2026-10-06')
            self.assertEqual(code,200)
            self.assertFalse(payload['authoritative'])
            self.assertEqual(payload['products']['all']['populated_bins'],1)
            self.assertEqual(len(payload['products']['all']['envelope_segments']),1)
            self.assertEqual(len(payload['products']['all']['envelope_segments'][0]),2)
            code,geo=self.request('/traffic-density/envelopes.geojson')
            self.assertEqual(code,200)
            self.assertEqual(geo['features'][0]['geometry']['type'],'LineString')
            self.assertEqual(self.request('/traffic-density/envelopes?start=bad')[0],400)
            bridge.home_marker=None
            self.assertEqual(self.request('/traffic-density/envelopes')[0],400)
            bridge.density_store.close()
            bridge.CFG['source']='swim_tfms'
            bridge.density_store=DensityStore(Path(self.temp.name)/'faa',source_type='swim_tfms')
            bridge.home_marker={'latitude':41,'longitude':-77}
            bridge.collect_density([self.ac],NOW)
            with patch.object(bridge,'flush_coverage') as flush:
                code,payload=self.request('/traffic-density/envelopes')
                self.assertEqual(code,200)
                self.assertIn('products',payload)
                flush.assert_not_called()
            self.assertEqual(self.request('/traffic-density.geojson')[0],200)
            code,page=self.request('/?density_view=1&zoom=11&max_cells=6000&bbox=-78,40,-76,43')
            self.assertEqual(code,200);self.assertIn('faa-density-state',page)
            self.assertEqual(self.request('/range-coverage')[0],404)
            code,page=self.request('/')
            self.assertIn('id="envelope-control" class="analysis-controls" hidden',page)
        finally:bridge.home_marker=original

if __name__=='__main__':unittest.main()
