"""Actual map-only airport HTTP lookup; no feed mutation or consumer credit."""
from unittest.mock import patch
import unittest
import test_density_bridge as fixture
bridge = fixture.bridge


class AirportHttpTests(unittest.TestCase):
    setUp = fixture.DensityBridgeTests.setUp
    tearDown = fixture.DensityBridgeTests.tearDown
    request = fixture.DensityBridgeTests.request

    def test_bounded_lookup_and_no_feed_mutation(self):
        with patch.object(bridge.feed_consumers, 'record') as record:
            original = bridge.latest_data
            status, data = self.request('/airport-lookup?codes=SYR,KSYR,ZZZZZZZZ')
            self.assertEqual(status, 200)
            self.assertEqual(data['airports']['SYR'], data['airports']['KSYR'])
            self.assertIsNone(data['airports']['ZZZZZZZZ'])
            self.assertIs(bridge.latest_data, original)
            record.assert_not_called()
        self.assertEqual(self.request('/airport-lookup?codes='+','.join(['SYR']*257))[0], 400)

    def test_lookup_failure_does_not_break_aircraft_feed(self):
        with patch.object(bridge.airport_lookup, 'lookup_many', side_effect=OSError('missing')):
            self.assertEqual(self.request('/airport-lookup?codes=SYR')[0], 503)
            self.assertEqual(self.request('/data/aircraft.json')[0], 200)


if __name__ == '__main__':unittest.main()
