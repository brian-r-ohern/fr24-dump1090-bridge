import sys,unittest
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'fr24-dump1090'))
from airport_context import classify_destination_movement
class Airports:
 def lookup_many(self,keys):return {k:dict(icao='KBOS',lat=42,lon=-71) for k in keys if k in ('BOS','KBOS')}
class DestinationTests(unittest.TestCase):
 def points(self,out=True):return [dict(t=i*12,lat=42,lon=-71.1+(-1 if out else 1)*i*.003,segment=1,destination_code='BOS',motion={}) for i in range(26)]
 def classify(self,s):return classify_destination_movement({'route_destination':'BOS'},s,Airports())
 def test_direction(self):
  s=self.points();self.assertTrue(self.classify(s)['sustained_movement_away']);self.assertEqual(self.classify(s)['direction'],'outbound')
  self.assertFalse(self.classify(s[-10:])['sustained_movement_away']);self.assertEqual(self.classify(self.points(False))['direction'],'inbound')
  for p in s:p['lon']=-71.1
  self.assertEqual(self.classify(s)['direction'],'crossing')
 def test_holding(self):
  s=self.points();s[-3]['motion']={'patterns':[{'name':'racetrack','status':'established'}]}
  self.assertTrue(self.classify(s)['divergence_suppressed']);self.assertFalse(self.classify(s)['sustained_movement_away'])
  s[-3]['motion']['patterns'][0]['status']='candidate';self.assertTrue(self.classify(s)['sustained_movement_away'])
 def test_reset(self):
  s=self.points();s[-1]['motion']['quality']='stale';self.assertIsNone(self.classify(s));s[-1]['motion']={};s[-1]['segment']=2;self.assertIsNone(self.classify(s))
  s=self.points();s[-3]['destination_code']='KBOS';self.assertIsNone(self.classify(s))
