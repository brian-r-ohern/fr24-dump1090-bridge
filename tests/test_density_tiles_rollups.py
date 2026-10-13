import contextlib
import copy
import io
import random
import tempfile
import unittest
import sys
from pathlib import Path
from unittest.mock import patch
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'fr24-dump1090'))
from traffic_density import DensityStore
class ParentTileTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.now=1791806400
        self.store=DensityStore(self.tmp.name,clock=lambda:self.now,source_type='sbs_30003')
    def tearDown(self):self.store.close();self.tmp.cleanup()
    def query(self,raw=False,**kwargs):
        self.store._rollups_enabled=not raw
        try:
            with contextlib.redirect_stdout(io.StringIO()):return self.store.query(bypass_cache=True,**kwargs)
        finally:self.store._rollups_enabled=True
    def view(self,**kwargs):
        with contextlib.redirect_stdout(io.StringIO()):return self.store.view(**kwargs)
    def fill(self):
        rng=random.Random(11)
        ac=[{'hex':str(i),'lat':rng.uniform(41.9,42.1),'lon':rng.uniform(-77.1,-76.9),'alt_baro':rng.choice([None,1000,1200,18000,40000])} for i in range(80)]
        for delta in (-12*86400,-86400,0):self.store.observe(ac,self.now+delta,'sbs_30003')
        return ac
    def assert_parent_equal(self):
        for zoom in (0,8,9,11,12,14,15,17):
            for band in ('all','low','middle,high'):
                actual=self.query(zoom=zoom,bands=band,max_cells=20,bbox=[-78,41,-76,43])
                expected=self.query(raw=True,zoom=zoom,bands=band,max_cells=20,bbox=[-78,41,-76,43])
                self.assertEqual(actual['cells'],expected['cells'],(zoom,band))
                self.assertEqual(actual['display_zoom'],expected['display_zoom'])
    def test_incremental_update_restore_and_reopen(self):
        ac=self.fill();self.assert_parent_equal()
        self.now+=60
        for i in range(4):self.store.observe(ac,self.now+i,'sbs_30003')
        ac.append({'hex':'new','lat':42.02,'lon':-77.02,'alt_baro':60000})
        self.store.observe(ac,self.now+5,'sbs_30003');self.assert_parent_equal()
        backup=self.store.export()
        changed=copy.deepcopy(backup)
        first=next(iter(changed['months']['2026-10']))
        for day,stats in first['days'].items():
            stats['last_observed']+=10
            stats['first_observed']=None;stats['history_complete']=False
        first['provenance']='new-origin'
        self.store.restore(changed);self.assert_parent_equal()
        self.store.close();self.store=DensityStore(self.tmp.name,clock=lambda:self.now,source_type='sbs_30003');self.assert_parent_equal()
    def test_deletion_and_nonmonotonic_update_rebuild(self):
        self.fill();self.assert_parent_equal()
        db=self.store._db('2026-10')
        row=db.execute('SELECT cell,day FROM daily LIMIT 1').fetchone()
        db.execute('DELETE FROM daily WHERE cell=? AND day=?',tuple(row));db.commit();self.assert_parent_equal()
        db.execute('UPDATE daily SET min_ft=min_ft+10 WHERE min_ft IS NOT NULL AND day="2026-10-12"');db.commit();self.assert_parent_equal()
    def test_tiles_match_view_and_expiry_forcing(self):
        ac=self.fill()
        for zoom in (8,11,14,17):
            for band in ('all','low','middle,high'):
                kwargs=dict(zoom=zoom,bbox=[-77.1,41.9,-76.9,42.1],bands=band,max_cells=20)
                with contextlib.redirect_stdout(io.StringIO()):expected=self.store.geojson(**kwargs,bypass_cache=True)
                first=self.view(**kwargs,bypass_cache=True);second=self.view(**kwargs)
                self.assertEqual(first['features'],expected['features'])
                self.assertEqual(second['features'],expected['features'])
                self.assertEqual(len({f['properties']['cell_id'] for f in second['features']}),len(second['features']))
                self.assertEqual(second['cache']['misses'],0)
        kwargs=dict(zoom=11,bbox=[-78,41,-76,43])
        before=self.view(**kwargs,bypass_cache=True)
        self.now+=1;self.store.observe(ac,self.now,'sbs_30003')
        cached=self.view(**kwargs);self.assertEqual(before['features'],cached['features'])
        forced=self.view(**kwargs,bypass_cache=True);self.assertNotEqual(forced['features'],cached['features'])
        self.now+=7201
        expired=self.view(**kwargs);self.assertGreater(expired['cache']['misses'],0)
    def test_restore_clear_cache_invalidation_and_bounds(self):
        self.fill();kwargs=dict(zoom=11,bbox=[-78,41,-76,43])
        self.view(**kwargs);self.assertTrue(self.store.tile_cache)
        self.store.restore(self.store.export());self.assertFalse(self.store.tile_cache)
        self.view(**kwargs)
        self.store.clear();self.assertFalse(self.store.tile_cache);self.assertEqual(self.view(**kwargs)['features'],[])
        self.fill()
        with patch('density_tiles.MAX_BYTES',100),patch('density_tiles.MAX_ENTRIES',2):
            self.view(**kwargs,bypass_cache=True)
            self.assertLessEqual(self.store.tile_cache_bytes,100)
            self.assertLessEqual(len(self.store.tile_cache),2)
    def test_boundaries_poles_and_empty_band(self):
        positions=[(0,0),(90,180),(-90,-180),(45,90),(-45,-90)]
        self.store.observe([{'hex':str(i),'lat':lat,'lon':lon} for i,(lat,lon) in enumerate(positions)],self.now,'sbs_30003')
        for box in ([-180,-90,180,90],[-1,-1,1,1],[89,44,90,45],[179,89,180,90],[-180,-90,-179,-89]):
            for zoom in (0,8,11,17):
                kwargs=dict(zoom=zoom,bbox=box,max_cells=5)
                with contextlib.redirect_stdout(io.StringIO()):expected=self.store.geojson(**kwargs,bypass_cache=True)
                self.assertEqual(self.view(**kwargs,bypass_cache=True)['features'],expected['features'],(box,zoom))
        self.assertEqual(self.view(zoom=11,bbox=[-1,-1,1,1],bands='none')['features'],[])
