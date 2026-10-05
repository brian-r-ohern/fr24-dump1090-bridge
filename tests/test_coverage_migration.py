import importlib
import json
import os
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'fr24-dump1090'))
_options = tempfile.TemporaryDirectory()
_options_path = Path(_options.name) / 'options.json'
_options_path.write_text(json.dumps({'receiver_host': 'localhost'}))
os.environ['FR24_OPTIONS_PATH'] = str(_options_path)
bridge = importlib.import_module('fr24_dump1090')


class CoverageMigrationTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        bridge.COVERAGE_PATH = str(Path(self.tmp.name) / 'range-coverage.json')
        bridge.coverage_bins = [None] * 720
        bridge.coverage_pending = []
        bridge.coverage_baseline = None
        bridge.coverage_loaded = True
        bridge.coverage_dirty = False
        bridge.coverage_generation = 0
        bridge.home_marker = {'latitude': 42, 'longitude': -77}
        bridge.CFG['source'] = 'sbs_30003'

    def tearDown(self):
        self.tmp.cleanup()

    def item(self, bearing, distance=200, actual=None):
        lon, lat = bridge._coverage_destination(bridge.home_marker, bearing if actual is None else actual, distance)
        return {'bearing': bearing, 'distance_nm': distance, 'latitude': lat, 'longitude': lon, 'observed': '2026-10-04T00:00:00Z'}

    def test_legacy_preserved_and_seeds_two_bins(self):
        payload = {'version': 2, 'bin_degrees': 1, 'bins': [self.item(10, actual=10.3), self.item(11, actual=10.7)]}
        original = json.dumps(payload, indent=2) + '\n'
        Path(bridge.COVERAGE_PATH).write_text(original)
        bridge.load_coverage()
        bridge.flush_coverage(force=True)
        self.assertEqual(Path(bridge.COVERAGE_PATH + '.1-degree-baseline.json').read_text(), original)
        self.assertEqual(bridge.coverage_baseline, payload)
        self.assertEqual([x['bearing'] for x in bridge.coverage_bins if x], [10, 10.5, 11, 11.5])
        bridge.load_coverage()
        self.assertEqual(bridge.coverage_baseline, payload)
        self.assertEqual(bridge.coverage_bins[21]['source_bin_degrees'], 1)

    def test_import_one_sector_seeds_adjacent_pair(self):
        result = bridge.import_coverage_payload({'bin_degrees': 1, 'bins': [self.item(10, actual=9.7)]})
        self.assertEqual(result['populated_bins'], 2)
        self.assertEqual(bridge.coverage_bins[20]['bearing'], 10)
        self.assertEqual(bridge.coverage_bins[21]['bearing'], 10.5)
        self.assertIsNone(bridge.coverage_bins[19])
        self.assertEqual(bridge.coverage_bins[21]['provenance'], 'legacy_adjacent_seed')

    def test_native_merge_and_invalid_import_are_atomic(self):
        payload = {'bin_degrees': 0.5, 'bins': [self.item(20.5)]}
        bridge.import_coverage_payload(payload)
        result = bridge.import_coverage_payload({'bin_degrees': 0.5, 'bins': [self.item(20.5, 100)]})
        self.assertEqual(result['retained'], 1)
        invalid = {'bin_degrees': 0.5, 'bins': [self.item(21), self.item(21.1)]}
        with self.assertRaises(ValueError):
            bridge.import_coverage_payload(invalid)
        self.assertIsNone(bridge.coverage_bins[42])

    def test_legacy_seed_without_home_and_restart(self):
        item = self.item(10, actual=10.3)
        bridge.home_marker = None
        result = bridge.import_coverage_payload({'bin_degrees': 1, 'bins': [item]})
        self.assertEqual(result['pending'], 0)
        self.assertEqual(result['populated_bins'], 2)
        bridge.load_coverage()
        self.assertEqual(len(bridge.coverage_pending), 0)
        self.assertIsNotNone(bridge.coverage_bins[20])
        self.assertIsNotNone(bridge.coverage_bins[21])

    def test_full_legacy_import_and_farther_live_replacement(self):
        bridge.import_coverage_payload({'bin_degrees': 1, 'bins': [self.item(i) for i in range(360)]})
        self.assertEqual(sum(x is not None for x in bridge.coverage_bins), 720)
        point = self.item(12.5, 250)
        bridge.latest_data = {'aircraft': [{'lat': point['latitude'], 'lon': point['longitude']}]}
        bridge.update_coverage_from_snapshot()
        self.assertEqual(bridge.coverage_bins[25]['provenance'], 'observed')
        self.assertEqual(bridge.coverage_bins[24]['provenance'], 'legacy_adjacent_seed')
        bridge.import_coverage_payload({'bin_degrees': 1, 'bins': [self.item(12)]})
        self.assertEqual(bridge.coverage_bins[25]['distance_nm'], 250)

    def test_existing_half_degree_install_reseeds_preserved_baseline(self):
        baseline = {'bin_degrees': 1, 'bins': [self.item(12)]}
        payload = {'bin_degrees': .5, 'bins': [self.item(12, 250)], 'baseline_1_degree': baseline}
        Path(bridge.COVERAGE_PATH).write_text(json.dumps(payload))
        bridge.load_coverage()
        self.assertEqual(bridge.coverage_bins[24]['distance_nm'], 250)
        self.assertEqual(bridge.coverage_bins[25]['distance_nm'], 200)

    def test_adjacent_real_observations_fill_distinct_half_degree_bins(self):
        points = [self.item(b) for b in (10, 10.5)]
        bridge.latest_data = {'aircraft': [{'lat': x['latitude'], 'lon': x['longitude']} for x in points]}
        bridge.update_coverage_from_snapshot()
        self.assertIsNotNone(bridge.coverage_bins[20])
        self.assertIsNotNone(bridge.coverage_bins[21])
        self.assertIsNone(bridge.coverage_bins[22])

    def test_gap_export_and_north_wrap_match_map(self):
        bridge.import_coverage_payload({'bin_degrees': 0.5, 'bins': [self.item(359.5), self.item(0), self.item(90)]})
        payload = bridge.coverage_payload()
        self.assertEqual(len(payload['envelope_segments']), 2)
        features = bridge.coverage_geojson_payload()['features']
        self.assertEqual(features[0]['geometry']['type'], 'MultiLineString')
        self.assertEqual(features[0]['geometry']['coordinates'], payload['envelope_segments'])
        self.assertEqual(len(features), 4)

    def test_complete_export_closed_polygon(self):
        bridge.import_coverage_payload({'bin_degrees': 0.5, 'bins': [self.item(i * .5) for i in range(720)]})
        geometry = bridge.coverage_geojson_payload()['features'][0]['geometry']
        self.assertEqual(geometry['type'], 'Polygon')
        self.assertEqual(geometry['coordinates'][0][0], geometry['coordinates'][0][-1])

    def test_bad_file_not_overwritten(self):
        Path(bridge.COVERAGE_PATH).write_text('broken')
        bridge.load_coverage()
        bridge.latest_data = {'aircraft': [{'lat': 42.1, 'lon': -77}]}
        bridge.update_coverage_from_snapshot()
        self.assertEqual(Path(bridge.COVERAGE_PATH).read_text(), 'broken')
        self.assertFalse(bridge.coverage_loaded)
