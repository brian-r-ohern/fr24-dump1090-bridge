import copy
import json
import sys
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'fr24-dump1090'))
from traffic_density import DensityStore, cell_id, parent, polygon, altitude_ft


def epoch(value):
    return datetime.fromisoformat(value).replace(tzinfo=timezone.utc).timestamp()


class DensityTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory()
        self.now=epoch('2026-10-05T12:00:00')
        self.store=DensityStore(self.temp.name,clock=lambda:self.now)

    def tearDown(self):
        self.store.close()
        self.temp.cleanup()

    def aircraft(self,altitude=1000,lon=-77,hex_id='aabbcc'):
        return {'hex':hex_id,'lat':42,'lon':lon,'alt_baro':altitude}

    def test_usable_altitude_fallback_and_polar_positions(self):
        self.assertEqual(altitude_ft({'alt_baro':'bad','alt_geom':1200}),1200)
        self.assertEqual(altitude_ft({'alt_baro':1000,'alt_geom':2000}),1000)
        self.store.observe([{**self.aircraft(),'lat':90},{**self.aircraft(hex_id='pole2'),'lat':-90}])
        self.assertEqual(sum(c['observation_count'] for c in self.store.query()['cells']),2)

    def test_bands_integrity_validity_and_no_interpolation(self):
        values=[-100,1199,1200,17999,18000,61200,None,'ground',float('nan')]
        self.store.observe([self.aircraft(a,hex_id=str(i)) for i,a in enumerate(values)])
        self.store.observe([self.aircraft(lon=-76.8)])
        bad=[{**self.aircraft(),'lat':None},{**self.aircraft(),'lat':91},{**self.aircraft(),'lon':float('nan')},{**self.aircraft(),'seen_pos':91}]
        self.store.observe(bad)
        cells=self.store.query()['cells']
        self.assertEqual(len(cells),2)
        cell=next(c for c in cells if c['observation_count']==9)
        self.assertEqual(cell['altitude'],{'below_1200_ft':3,'1200_to_17999_ft':2,'18000_ft_and_above':2,'unknown':2,'min_ft':-100,'max_ft':61200})
        self.assertEqual(sum(c['observation_count'] for c in cells),10)
        for c in cells:
            self.assertEqual(c['observation_count'],sum(c['altitude'][k] for k in ('below_1200_ft','1200_to_17999_ft','18000_ft_and_above','unknown')))

    def test_passage_jitter_dropout_and_continuous_occupancy(self):
        a=self.aircraft()
        b=self.aircraft(lon=-76.99)
        for item in (a,b,a,b,a):
            self.store.observe([item]);self.now+=1
        self.assertEqual(sum(c['passage_count'] for c in self.store.query()['cells']),2)
        self.now+=50;self.store.observe([a])
        self.assertEqual(sum(c['passage_count'] for c in self.store.query()['cells']),2)
        for _ in range(100):
            self.now+=1;self.store.observe([a])
        self.assertEqual(sum(c['passage_count'] for c in self.store.query()['cells']),2)
        self.now+=91;self.store.observe([a])
        self.assertEqual(sum(c['passage_count'] for c in self.store.query()['cells']),3)

    def test_month_boundary_daily_window_parent_and_reopen(self):
        self.now=epoch('2026-09-30T23:59:59');self.store.observe([self.aircraft()])
        self.now+=2;self.store.observe([self.aircraft(18000)])
        self.assertEqual(len(self.store.export()['months']),2)
        self.assertEqual(self.store.query(start='2026-10-01',end='2026-10-01')['cells'][0]['observation_count'],1)
        coarse=self.store.query(zoom=15)
        self.assertEqual(coarse['cells'][0]['observation_count'],2)
        self.assertEqual(coarse['cells'][0]['cell_id'],parent(cell_id(42,-77),15))
        self.assertEqual(len(self.store.geojson()['features'][0]['geometry']['coordinates'][0]),5)
        self.store.close();self.store=DensityStore(self.temp.name,clock=lambda:self.now)
        self.assertEqual(self.store.query()['cells'][0]['observation_count'],2)

    def test_roundtrip_repeat_restore_older_and_newer_snapshot(self):
        self.store.observe([self.aircraft()]);old=self.store.export()
        self.now+=10;self.store.observe([self.aircraft()]);new=self.store.export()
        self.store.restore(old)
        self.assertEqual(self.store.query()['cells'][0]['observation_count'],2)
        with tempfile.TemporaryDirectory() as target:
            other=DensityStore(target,clock=lambda:self.now)
            try:
                other.restore(old);other.restore(new);other.restore(new)
                self.assertEqual(other.query()['cells'][0]['observation_count'],2)
                self.assertEqual(other.export()['months'],new['months'])
            finally:other.close()

    def test_cross_origin_conflict_is_not_additive_and_uncertain(self):
        self.store.observe([self.aircraft()]);backup=self.store.export()
        cell=backup['months']['2026-10'][0]
        cell['provenance']='different-origin'
        cell['days']['2026-10-05']['last_observed']+=1
        self.store.restore(backup);self.store.restore(backup)
        result=self.store.query()['cells'][0]
        self.assertEqual(result['observation_count'],1)
        self.assertFalse(result['history_complete'])
        self.assertIsNone(result['first_observed'])
        self.now+=20;self.store.observe([self.aircraft()])
        result=self.store.query()['cells'][0]
        self.assertEqual(result['observation_count'],2)
        self.assertIsNone(result['first_observed'])
        self.assertFalse(result['history_complete'])

    def test_conflict_order_and_equal_timestamp_are_deterministic(self):
        self.store.observe([self.aircraft()]);a=self.store.export();b=copy.deepcopy(a)
        stats=b['months']['2026-10'][0]['days']['2026-10-05']
        stats['observation_count']=2;stats['below_1200_ft']=2
        results=[]
        for order in ((a,b),(b,a)):
            with tempfile.TemporaryDirectory() as temp:
                store=DensityStore(temp,clock=lambda:self.now)
                try:
                    for payload in order:store.restore(payload)
                    before=store.export()['months']
                    for payload in order:store.restore(payload)
                    self.assertEqual(before,store.export()['months'])
                    results.append(before)
                finally:store.close()
        self.assertEqual(results[0],results[1])
        b=copy.deepcopy(a)
        b['months']['2026-10'][0]['provenance']='other-origin'
        results=[]
        for order in ((a,b),(b,a)):
            with tempfile.TemporaryDirectory() as temp:
                store=DensityStore(temp,clock=lambda:self.now)
                try:
                    for payload in order:store.restore(payload)
                    results.append(store.export()['months'])
                finally:store.close()
        self.assertEqual(results[0],results[1])

    def test_validation_before_mutation(self):
        self.store.observe([self.aircraft()]);original=self.store.export()
        for mutate in (
            lambda p:p.update(base_zoom=16),
            lambda p:p['months']['2026-10'][0]['days']['2026-10-05'].update(unknown=10),
            lambda p:p['months']['2026-10'].append(p['months']['2026-10'][0]),
            lambda p:p['months']['2026-10'][0]['days']['2026-10-05'].update(last_observed=float('nan')),
            lambda p:p['months']['2026-10'][0]['days']['2026-10-05'].update(first_observed=0),
        ):
            bad=copy.deepcopy(original);mutate(bad)
            with self.assertRaises(ValueError):self.store.restore(bad)
            self.assertEqual(original['months'],self.store.export()['months'])

    def test_retention_calendar_horizon_and_import_prune(self):
        self.now=epoch('2025-05-01T12:00:00');self.store.observe([self.aircraft()]);old=self.store.export()
        self.now=epoch('2026-10-05T12:00:00');self.store.observe([self.aircraft()])
        self.assertIn('2025-05',self.store.export()['months'])
        self.now=epoch('2026-11-01T12:00:00');self.store.prune()
        self.assertNotIn('2025-05',self.store.export()['months'])
        self.assertEqual(self.store.restore(old)['ignored_months'],1)
        self.assertFalse((Path(self.temp.name)/'2025-05.dat').exists())

    def test_corruption_protected_and_bounds(self):
        self.store.observe([self.aircraft()]);self.store.close()
        path=Path(self.temp.name)/'2026-10.dat';path.write_bytes(b'broken')
        with self.assertRaises(Exception):DensityStore(self.temp.name,clock=lambda:self.now)
        self.assertEqual(path.read_bytes(),b'broken')
        with self.assertRaises(ValueError):self.store.query(zoom=19)
        with self.assertRaises(ValueError):self.store.query(bbox=[5,0,-5,10])
        self.assertEqual(polygon('0/0/0')[0][0],-180)
        self.assertEqual(cell_id(90,180),'17/131071/0')
        self.assertEqual(cell_id(-90,-180),'17/0/131071')

if __name__=='__main__':unittest.main()
