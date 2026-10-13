import json,tempfile,unittest
from pathlib import Path
from unittest.mock import patch
from bridge_config import validate_options
from bridge_settings import checked_options,save_snapshot,read_snapshot
import test_density_bridge as fixture
bridge=fixture.bridge

class ThemeSettingsTests(unittest.TestCase):
    def test_default_choices_invalid_and_recovery(self):
        base={'receiver_host':'receiver'}
        self.assertEqual(validate_options(base)['map_theme'],'auto')
        self.assertEqual(checked_options(base)['map_theme'],'auto')
        for theme in ('auto','light','dark'):
            options={**base,'map_theme':theme}
            self.assertEqual(validate_options(options)['map_theme'],theme)
            self.assertEqual(checked_options(options)['map_theme'],theme)
            with tempfile.TemporaryDirectory() as folder:
                path=Path(folder);(path/'options.json').write_text(json.dumps(options))
                with patch.dict('os.environ',{'FR24_OPTIONS_PATH':str(path/'options.json'),'FR24_SETTINGS_PATH':str(path/'saved.json')}):
                    save_snapshot();self.assertEqual(read_snapshot()['options']['map_theme'],theme)
        for value in ('sepia','',None,1,True):
            with self.assertRaises(ValueError):validate_options({**base,'map_theme':value})
            with self.assertRaises(ValueError):checked_options({**base,'map_theme':value})

class ThemeHttpTests(unittest.TestCase):
    setUp=fixture.DensityBridgeTests.setUp
    tearDown=fixture.DensityBridgeTests.tearDown
    request=fixture.DensityBridgeTests.request
    def test_config_exposes_choice_and_initial_html_for_all_sources(self):
        original=bridge.CFG.copy()
        try:
            for source in ('sbs_30003','swim_sfdps'):
                bridge.CFG['source']=source
                for theme in ('auto','light','dark'):
                    bridge.CFG['map_theme']=theme
                    self.assertEqual(self.request('/map-config')[1]['map_theme'],theme)
                    from urllib.request import urlopen
                    with urlopen(self.base+'/',timeout=5) as response:page=response.read().decode()
                    self.assertIn('data-map-theme="'+theme+'"',page)
                    self.assertNotIn('__MAP_THEME__',page)
        finally:bridge.CFG.clear();bridge.CFG.update(original)
