import sys,sqlite3,random,unittest,importlib.util,tempfile
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'fr24-dump1090'))
from traffic_density import SCHEMA,polygon,BAND_FIELDS
from density_envelopes import distance_bearing
from density_envelope_batches import reduce_batches

def scalar(rows,home):
 products={b:{} for b in ('all','low','middle','high')}
 for row in rows:
  ring=polygon(row['cell']);lon=(ring[0][0]+ring[1][0])/2;lat=(ring[0][1]+ring[2][1])/2
  distance,bearing=distance_bearing(home,lat,lon);index=int((bearing+.25)/.5)%720
  for band,bins in products.items():
   count=row['observation_count'] if band=='all' else row[BAND_FIELDS[band]]
   if not count:continue
   sector=bins.setdefault(index,dict(bearing=index*.5,observation_count=0,qualifying_cell_passage_count=0,occupied_cell_count=0,distance_nm=-1,furthest_cell_id=None,furthest_cell_observation_count=0,history_complete=True))
   sector['observation_count']+=count;sector['qualifying_cell_passage_count']+=row['passage_count'];sector['occupied_cell_count']+=1
   sector['history_complete']=sector['history_complete'] and bool(row['history_complete'])
   if distance>sector['distance_nm']:sector.update(distance_nm=distance,furthest_cell_id=row['cell'],furthest_cell_observation_count=count,cell_center=[lon,lat])
 return products

class BatchTests(unittest.TestCase):
 def test_global_cells_and_batch_boundaries_match_scalar(self):
  rng=random.Random(37);db=sqlite3.connect(':memory:');db.row_factory=sqlite3.Row;db.executescript(SCHEMA)
  coords={(rng.randrange(131072),rng.randrange(131072)) for _ in range(4000)}
  coords.update((x,y) for x in (65534,65535,65536,65537) for y in (65534,65535,65536,65537))
  for x,y in sorted(coords):
   counts=[rng.randrange(5) for _ in range(4)]
   db.execute('INSERT INTO daily VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)',(f'17/{x}/{y}','window',sum(counts),rng.randrange(10),*counts,None,None,None,1,rng.randrange(2)))
  rows=db.execute('SELECT * FROM daily ORDER BY cell').fetchall()
  for home in ({'latitude':0,'longitude':0},{'latitude':43.06,'longitude':-75.77},{'latitude':89.9,'longitude':179.9}):
   expected=scalar(rows,home)
   for batch in (257,65536):
    products={b:{} for b in expected};cells,_=reduce_batches(db,home,products,distance_bearing,lambda *a,**kw:None,batch)
    self.assertEqual(cells,len(rows));self.assertEqual(products,expected)
  db.close()
 def test_empty(self):
  db=sqlite3.connect(':memory:');db.row_factory=sqlite3.Row;db.executescript(SCHEMA);products={b:{} for b in ('all','low','middle','high')}
  self.assertEqual(reduce_batches(db,{'latitude':0,'longitude':0},products,distance_bearing,lambda *a,**k:None),(0,0));db.close()
