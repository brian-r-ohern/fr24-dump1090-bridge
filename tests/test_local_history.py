import sys,tempfile,unittest
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'fr24-dump1090'))
from local_history import LocalHistory,DAY
class Airports:
 def lookup_many(self,codes):return {c:{'icao':c,'lat':0,'lon':0 if c=='A' else 1} for c in codes if c in ('A','B')}
class LocalTests(unittest.TestCase):
 def test_backfill_append_restart_expiry_and_remote(self):
  with tempfile.TemporaryDirectory() as path:
   store=LocalHistory(path,'sbs_30003');airports=Airports()
   identity={'route_origin':'A','route_destination':'B','flight':'LOCAL'}
   def row(t,lon):return {'t':t,'received_at':t,'lat':0,'lon':lon,'segment':1}
   track={'identity':identity,'samples':[row(100,.5),row(110,0)]}
   store.retain({'x':track},110,airports,lambda a:True)
   track['samples'].append(row(120,.3));store.retain({'x':track},125,airports,lambda a:False)
   self.assertEqual(len(LocalHistory(path,'sbs_30003').snapshot(125)['x']['samples']),3)
   store.retain({},DAY+130,airports,lambda a:True);self.assertEqual(store.snapshot(DAY+130),{})
   store.retain({'x':track},125,airports,lambda a:a['icao']=='A');self.assertEqual(store.snapshot(125),{})
 def test_endpoint_observation_and_source_isolation(self):
  with tempfile.TemporaryDirectory() as path:
   store=LocalHistory(path,'sbs_30003');track={'identity':{'route_origin':'A','route_destination':'B'},'samples':[{'t':100,'received_at':100,'lat':0,'lon':.5}]}
   store.retain({'x':track},100,Airports(),lambda a:True);self.assertEqual(store.snapshot(100),{})
   track['samples'][0]['lon']=0;store.retain({'x':track},100,Airports(),lambda a:True)
   self.assertEqual(len(store.snapshot(100)),1);self.assertEqual(LocalHistory(path,'swim_sfdps').snapshot(100),{})
if __name__=='__main__':unittest.main()
