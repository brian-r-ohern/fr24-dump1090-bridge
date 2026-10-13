"""Airport identifier correctness and reference-data fallback behavior."""
import json
from pathlib import Path
import sys
import tempfile
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]/'fr24-dump1090'))
from airport_lookup import AirportLookup


class AirportLookupTests(unittest.TestCase):
    def test_bundled_iata_icao_and_unknown(self):
        lookup=AirportLookup(Path(__file__).resolve().parents[1]/'fr24-dump1090/airports.json')
        result=lookup.lookup_many(['syr',' KSYR ','JFK','KJFK','KEWR','ZZZZZZZZ'])
        self.assertEqual(result['SYR'], result['KSYR'])
        self.assertEqual(result['JFK'], result['KJFK'])
        self.assertAlmostEqual(result['KSYR']['lat'],43.11,delta=.03)
        self.assertAlmostEqual(result['KSYR']['lon'],-76.11,delta=.03)
        self.assertIsNone(result['ZZZZZZZZ'])

    def test_ambiguity_coordinates_exact_identifiers_and_load_once(self):
        with tempfile.TemporaryDirectory() as temp:
            path=Path(temp)/'airports.json'
            path.write_text(json.dumps([
                {'icao':'KAAA','iata':'XYZ','name':'One','lat':0,'lon':0,'ident':'LOCAL1'},
                {'icao':'KBBB','iata':'XYZ','name':'Two','lat':1,'lon':1},
                {'icao':'KBAD','iata':'BAD','lat':91,'lon':0},
                {'icao':'KBOOL','iata':'BOL','lat':True,'lon':0},
                {'icao':'KDUP','iata':'DUP','lat':0,'lon':0},
                {'icao':'KDUP','iata':'DUP','lat':1,'lon':1}]))
            lookup=AirportLookup(path);r=lookup.lookup_many(['XYZ','KAAA','LOCAL1','KBAD','KBOOL','KDUP','DUP','https://x'])
            self.assertIsNone(r['XYZ']);self.assertEqual(r['KAAA']['lat'],0)
            self.assertEqual(r['KAAA'],r['LOCAL1'])
            for code in ['KBAD','KBOOL','KDUP','DUP']:self.assertIsNone(r[code])
            self.assertNotIn('https://x',r)
            path.unlink();self.assertEqual(lookup.lookup_many(['KAAA'])['KAAA'],r['KAAA'])
            with self.assertRaises(ValueError):lookup.lookup_many(['SYR']*257)


if __name__=='__main__':unittest.main()
