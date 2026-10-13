"""CSV conversion preserves coordinate order and excludes unusable airports."""
import csv
import importlib.util
from pathlib import Path
import tempfile
import unittest

spec = importlib.util.spec_from_file_location('airport_converter', Path(__file__).resolve().parents[1] / 'tools/build_airport_lookup.py')
converter = importlib.util.module_from_spec(spec)
spec.loader.exec_module(converter)


class AirportConversionTests(unittest.TestCase):
    def test_csv_coordinates_aliases_closed_and_invalid(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'airports.csv'
            with path.open('w', newline='') as stream:
                writer = csv.DictWriter(stream, fieldnames=['type', 'ident', 'icao_code', 'gps_code', 'iata_code', 'name', 'coordinates','elevation_ft'])
                writer.writeheader()
                writer.writerows([
                    {'type': 'large_airport', 'ident': 'KJFK', 'icao_code': 'KJFK', 'gps_code': 'KJFK', 'iata_code': 'JFK', 'name': 'JFK', 'coordinates': '40.64, -73.78','elevation_ft':'13'},
                    {'type': 'heliport', 'ident': '00A', 'gps_code': 'K00A', 'coordinates': '40.07, -74.93'},
                    {'type': 'closed', 'ident': 'OLD', 'coordinates': '0, 0'},
                    {'type': 'small_airport', 'ident': 'BAD', 'coordinates': 'NaN, 0'},
                    {'type': 'small_airport', 'ident': 'RANGE', 'coordinates': '91, 0'},
                    {'type': 'small_airport', 'ident': 'NONE', 'coordinates': ''},
                ])
            records = converter.convert(path)
            self.assertEqual(len(records), 2)
            self.assertEqual(records[0]['elevation_ft'],13)
            self.assertEqual(records[0]['airport_type'],'large_airport')
            self.assertIsNone(records[1]['elevation_ft'])
            self.assertEqual((records[0]['lat'], records[0]['lon']), (40.64, -73.78))
            self.assertEqual((records[0]['icao'], records[0]['iata']), ('KJFK', 'JFK'))
            self.assertEqual((records[1]['icao'], records[1]['ident']), ('K00A', '00A'))
