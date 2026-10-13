import sys,tempfile,unittest
from pathlib import Path
from unittest.mock import patch
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'fr24-dump1090'))
from traffic_density import DensityStore
from motion_state import MotionEngine

class CacheInventoryTests(unittest.TestCase):
    def test_missing_built_expired_and_band_changes_without_queries(self):
        with tempfile.TemporaryDirectory() as temp:
            now=[1791800000.0]
            store=DensityStore(temp,source_type='sbs_30003',clock=lambda:now[0])
            options={'zoom':11,'bbox':[-78,41,-76,43],'bands':'all'}
            missing=store.cache_status(**options)
            self.assertGreater(missing['to_build'],0)
            view=store.view(**options)
            complete=view['cache']['inventory']
            self.assertEqual(complete['cached'],missing['to_build']);self.assertEqual(complete['to_build'],0)
            with patch.object(store,'query',side_effect=AssertionError('Inventory must not query observations')):
                self.assertEqual(store.cache_status(**options),complete)
                changed=store.cache_status(**{**options,'bands':'high'})
                self.assertEqual(changed['to_build'],complete['cached'])
                now[0]+=7200
                expired=store.cache_status(**options)
                self.assertEqual(expired['stale'],complete['cached']);self.assertEqual(expired['cached'],0)
                self.assertNotIn('features',expired)
            store.clear()
            self.assertEqual(store.cache_status(**options)['stale'],0)
            self.assertEqual(store.cache_status(**options)['to_build'],complete['cached'])

class SfdpsMotionTests(unittest.TestCase):
    def test_independent_reports_and_reported_speed_not_ground_speed(self):
        now=[1791800000.0];engine=MotionEngine('swim_sfdps',clock=lambda:now[0])
        for i in range(7):
            now[0]=1791800000+i*12
            ac={'hex':'sfdps-track','lat':42,'lon':-77+i*.01,'gs':1500,'alt_baro':5000}
            metadata={'sfdps-track':{'position_time':now[0],'time_basis':'sfdps_report_time','alt_baro_time':now[0],'altitude_reference':'sfdps_reported_altitude'}}
            engine.observe([ac],now[0],now[0],metadata)
            engine.observe([ac],now[0]+1,now[0]+1,metadata)
        self.assertEqual(engine.counters['accepted'],7)
        self.assertEqual(engine.counters['duplicates'],7)
        state=engine.snapshot()['aircraft']['sfdps-track']
        self.assertEqual(state['quality'],'supported')
        self.assertLess(state['metrics']['ground_speed_knots'],200)
        self.assertEqual(engine.tracks['sfdps-track']['samples'][-1]['reference'],'sfdps_reported_altitude')
        now[0]+=60
        ac['lon']+=.01
        engine.observe([ac],now[0],now[0],{'sfdps-track':{'position_time':now[0]}})
        self.assertEqual(engine.counters['gaps'],1)
        self.assertEqual(engine.snapshot()['aircraft']['sfdps-track']['quality'],'warming_up')

    def test_missing_report_time_rejected_and_tfms_excluded(self):
        engine=MotionEngine('swim_sfdps')
        engine.observe([{'hex':'x','lat':42,'lon':-77}],1791800000,1791800000)
        self.assertEqual(engine.rejection_reasons['missing_report_time'],1)
        self.assertEqual(engine.counters['accepted'],0)
        self.assertFalse(MotionEngine('swim_tfms').status()['available'])
