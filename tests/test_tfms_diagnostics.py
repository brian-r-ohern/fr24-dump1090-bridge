import sys
import unittest
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'fr24-dump1090'))
from swim_tfms import parse_tfms_tracks

class DiagnosticsTests(unittest.TestCase):
    def test_stages_and_namespace(self):
        xml = """<root xmlns:t="urn:test">
        <t:fltdMessage><t:msgType>flightPlan</t:msgType></t:fltdMessage>
        <t:fltdMessage><t:msgType>trackInformation</t:msgType><t:latitude>42</t:latitude><t:longitude>-77</t:longitude></t:fltdMessage>
        <t:fltdMessage><t:msgType>trackInformation</t:msgType><t:latitude>invalid</t:latitude></t:fltdMessage>
        <t:fltdMessage secret="hidden"><t:unknown>private</t:unknown></t:fltdMessage>
        </root>"""
        diag = {}
        records, count = parse_tfms_tracks(xml, diag)
        self.assertEqual((count, len(records)), (4, 1))
        self.assertEqual(diag['track_information'], 2)
        self.assertEqual(diag['positioned_tracks'], 1)
        self.assertEqual(diag['missing_latitude'], 1)
        self.assertEqual(diag['missing_longitude'], 1)
        self.assertEqual(diag['message_types'], {'flightplan':1,'trackinformation':2,'(missing)':1})
        self.assertNotIn('private', str(diag))
        self.assertNotIn('hidden', str(diag))
        self.assertEqual(parse_tfms_tracks(xml), (records, count))

    def test_attribute_structure_and_type_bound(self):
        xml = '<root>' + ''.join('<fltdMessage sourceFacility="secret"><msgType>type%d</msgType></fltdMessage>' % i for i in range(100)) + '</root>'
        diag = {}
        parse_tfms_tracks(xml, diag)
        self.assertLessEqual(len(diag['message_types']), 33)
        self.assertEqual(sum(diag['message_types'].values()), 100)
        self.assertIn('fltdmessage[sourcefacility]', diag['first_message_structure'])
        self.assertNotIn('secret', str(diag))

    def test_live_attribute_shape(self):
        xml = """<fltdMessage xmlns="urn:tfms" msgType="trackInformation" acid="TEST123" flightRef="REF1">
        <trackInformation><ncsmTrackData><position>
        <latitude><latitudeDMS degrees="42" minutes="30" seconds="0" direction="NORTH"/></latitude>
        <longitude><longitudeDMS degrees="77" minutes="15" seconds="0" direction="WEST"/></longitude>
        </position><nextEvent latitudeDecimal="1" longitudeDecimal="2"/>
        </ncsmTrackData></trackInformation></fltdMessage>"""
        diag = {}
        records, count = parse_tfms_tracks(xml, diag)
        self.assertEqual(count, 1)
        self.assertEqual(records[0]['lat'], 42.5)
        self.assertEqual(records[0]['lon'], -77.25)
        self.assertEqual(records[0]['flight'], 'TEST123')
        self.assertEqual(records[0]['_tfms_flight_ref'], 'REF1')
        self.assertEqual(diag['message_types'], {'trackinformation': 1})
        self.assertEqual(diag['positioned_tracks'], 1)
        for bad in ('minutes="60"', 'minutes="nan"'):
            records, _ = parse_tfms_tracks(xml.replace('minutes="30"', bad))
            self.assertEqual(records, [])
        records, _ = parse_tfms_tracks(xml.replace('msgType="trackInformation"', 'msgType="flightPlan"'))
        self.assertEqual(records, [])

    def test_bad_xml(self):
        with self.assertRaises(Exception):
            parse_tfms_tracks('<broken')

if __name__ == '__main__':
    unittest.main()
