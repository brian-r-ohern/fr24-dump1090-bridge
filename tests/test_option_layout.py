"""Configuration layout migration preserves feeds, values and secret references."""
import io,json,os,sys,tempfile,unittest
from pathlib import Path
from unittest.mock import patch
import yaml
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'fr24-dump1090'))
from option_layout import flatten_options,grouped_options,needs_migration,GROUPS,MOVED
from bridge_config import validate_options
import bridge_settings as settings
class LayoutTests(unittest.TestCase):
 def sources(self):
  return [dict(source='sbs_30003',receiver_host='192.168.0.165'),dict(source='flights_js',receiver_host='rx',username='user',password='secret'),dict(source='aircraft_json',aircraft_json_url='http://rx/aircraft.json'),*[dict(source=source,swim_host='host',swim_vpn='vpn',swim_username='user',swim_password='secret',swim_queue='queue') for source in ('swim_tfms','swim_sfdps')]]
 def test_all_sources_equivalent_and_idempotent(self):
  for original in self.sources():
   original.update(map_theme='dark',development_recording=True,history_url='http://history:8756',tracker_aircraft_entity='sensor.custom')
   grouped=grouped_options(original)
   self.assertEqual(validate_options(original),validate_options(grouped))
   self.assertEqual(settings.checked_options(original),settings.checked_options(grouped))
   self.assertEqual(grouped_options(grouped),grouped)
 def test_legacy_over_new_defaults(self):
  config=yaml.safe_load((Path(__file__).resolve().parents[1]/'fr24-dump1090/config.yaml').read_text())
  mixed={**config['options'],**self.sources()[-1],'map_theme':'dark','trusted_networks':'192.168.0.0/24'}
  result=validate_options(mixed)
  self.assertEqual(result['source'],'swim_sfdps');self.assertEqual(result['map_theme'],'dark');self.assertEqual(result['trusted_networks'],'192.168.0.0/24')
  self.assertTrue(needs_migration(mixed));self.assertFalse(needs_migration(grouped_options(mixed)))
 def test_bad_groups(self):
  for extra in ({'faa_swim':[]},{'faa_swim':{'password':'bad'}},{'advanced':{'unknown':1}}):
   with self.assertRaises(ValueError):settings.checked_options({'receiver_host':'rx',**extra})
 def test_migration_secret_references(self):
  with tempfile.TemporaryDirectory() as root:
   path=Path(root)/'options.json';rendered={**self.sources()[-1],'swim_password':'resolved-value','history_url':'http://history','swim_retry_count':0};stored={**rendered,'swim_password':'!secret faa_password'};path.write_text(json.dumps(rendered))
   with patch.dict(os.environ,FR24_OPTIONS_PATH=str(path),SUPERVISOR_TOKEN='token'),patch.object(settings,'urlopen',side_effect=[io.BytesIO(json.dumps({'result':'ok','data':{'options':stored}}).encode()),io.BytesIO(b'{"result":"ok"}')]) as upstream:self.assertTrue(settings.migrate_options())
   request=upstream.call_args.args[0];payload=json.loads(request.data)['options']
   self.assertEqual(payload['faa_swim']['swim_password'],'!secret faa_password');self.assertEqual(payload['advanced']['swim_retry_count'],0);self.assertNotIn('resolved-value',request.data.decode());self.assertEqual(json.loads(path.read_text()),rendered)
 def test_layout_mapping(self):
  p=Path(__file__).resolve().parents[1]/'fr24-dump1090';config=yaml.safe_load((p/'config.yaml').read_text());tr=yaml.safe_load((p/'translations/en.yaml').read_text())['configuration']
  self.assertEqual(list(config['options'])[:3],['source','receiver_host','destination_airport']);self.assertEqual(list(GROUPS)[-1],'advanced');self.assertFalse(config['options']['advanced']['development_recording'])
  for group,keys in GROUPS.items():self.assertEqual(set(config['schema'][group]),set(keys));self.assertEqual(set(tr[group]['fields']),set(keys))
  self.assertEqual(set(GROUPS)-set(config['options']),set())
  self.assertEqual(set(GROUPS)-set(grouped_options({'source':'sbs_30003','receiver_host':'rx'})),set())
  self.assertFalse(MOVED & set(config['options']));self.assertNotIn('swim_product',config['options'])
if __name__=='__main__':unittest.main()
