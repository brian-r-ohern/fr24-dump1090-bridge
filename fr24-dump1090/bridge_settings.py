"""Explicit recovery of a retained settings snapshot through Supervisor."""
import json
import os
import secrets
import tempfile
import threading
from datetime import datetime, timezone
from html import escape
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

from bridge_config import validate_options

VERSION = '0.6.8'
TOKEN = secrets.token_urlsafe(32)
LOCK = threading.RLock()
LIMIT = 65536


def options_path():
    return Path(os.environ.get('FR24_OPTIONS_PATH', '/data/options.json'))


def snapshot_path():
    return Path(os.environ.get('FR24_SETTINGS_PATH', '/config/bridge-settings.json'))


def read_options():
    return json.loads(options_path().read_text(encoding='utf-8'))


def checked_options(options):
    defaults = json.loads(Path(__file__).with_name('settings_defaults.json').read_text())
    if not isinstance(options, dict) or set(options) - set(defaults):
        raise ValueError('Settings contain unsupported fields')
    merged = {**defaults, **options}
    for key, default in defaults.items():
        value = merged[key]
        if isinstance(default, str):
            if not isinstance(value, str):
                raise ValueError('Invalid settings field: ' + key)
        elif isinstance(value, bool) or not isinstance(value, int):
            raise ValueError('Invalid settings field: ' + key)
    limits = {'receiver_port': (1, 65535), 'sbs_port': (1, 65535),
              'poll_interval': (1, 60), 'request_timeout': (1, 30),
              'aircraft_json_poll_interval': (1, 60), 'swim_radius_nm': (25, 1000),
              'swim_aircraft_timeout': (30, 900), 'swim_retry_count': (0, 20),
              'swim_retry_interval_ms': (500, 60000)}
    for key, (minimum, maximum) in limits.items():
        if not minimum <= merged[key] <= maximum:
            raise ValueError('Invalid settings field: ' + key)
    if merged['density_legacy_source'] not in ('unassigned', 'sbs_30003', 'flights_js', 'aircraft_json', 'swim_tfms') or merged['swim_product'] != 'tfms':
        raise ValueError('Invalid source attribution or SWIM product')
    validate_options(merged)
    return merged


def read_snapshot():
    path = snapshot_path()
    if path.stat().st_size > LIMIT:
        raise ValueError('Settings snapshot is too large')
    payload = json.loads(path.read_text(encoding='utf-8'))
    if payload.get('schema_version') != 1 or payload.get('dataset') != 'bridge-settings':
        raise ValueError('Unsupported settings snapshot')
    payload['options'] = checked_options(payload.get('options'))
    return payload


def save_snapshot():
    """Never save defaults/incomplete settings over a useful retained snapshot."""
    with LOCK:
        options = checked_options(read_options())
        path = snapshot_path()
        if not path.parent.is_dir():
            raise ValueError('Persistent settings folder is unavailable')
        if path.exists():
            previous = read_snapshot()
            if previous['options'] == options:
                return previous
        payload = {'schema_version': 1, 'dataset': 'bridge-settings',
                   'build_version': VERSION, 'saved_at': datetime.now(timezone.utc).isoformat(),
                   'options': options}
        descriptor, temporary = tempfile.mkstemp(prefix='.bridge-settings-', dir=path.parent)
        try:
            with os.fdopen(descriptor, 'w', encoding='utf-8') as handle:
                json.dump(payload, handle, indent=2, allow_nan=False)
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(temporary, path)  # mkstemp uses owner-only permissions.
        finally:
            if os.path.exists(temporary):
                os.unlink(temporary)
        return payload


def restore_snapshot():
    with LOCK:
        payload = read_snapshot()
        token = os.environ.get('SUPERVISOR_TOKEN')
        if not token:
            raise ValueError('Supervisor is unavailable; use the host snapshot to recover configuration manually')
        request = Request('http://supervisor/addons/self/options',
                          data=json.dumps({'options': payload['options']}).encode(),
                          headers={'Authorization': 'Bearer ' + token, 'Content-Type': 'application/json'},
                          method='POST')
        try:
            with urlopen(request, timeout=15) as response:
                result = json.load(response)
            if result.get('result') != 'ok':
                raise ValueError('Supervisor rejected the settings restore; check Supervisor logs')
        except (HTTPError, URLError, TimeoutError):
            # Supervisor errors can contain option values. Never reflect them to the browser/log.
            raise ValueError('Supervisor could not restore settings; check Supervisor logs') from None
        return {'ok': True, 'restart_required': True,
                'message': 'Settings restored in Home Assistant. Restart this App to use them.'}


def settings_page(recovery_error=None):
    try:
        with LOCK:
            snapshot = read_snapshot()
        summary = ('Saved ' + str(snapshot.get('saved_at', 'unknown date')) + ' · source ' +
                   snapshot['options']['source'] + ' · build ' + str(snapshot.get('build_version', 'unknown')))
        available = True
    except FileNotFoundError:
        summary, available = 'No retained settings snapshot yet.', False
    except (ValueError, OSError, TypeError, AttributeError):
        summary, available = 'Retained settings snapshot is unreadable; it has been preserved.', False
    try:
        checked_options(read_options())
        can_save = True
    except (ValueError, OSError, TypeError):
        can_save = False
    error = ('<p>Collection is paused because feed settings are incomplete or invalid. Restore the saved settings, '
             'or configure the App in Home Assistant, then restart it.</p>') if recovery_error else ''
    return '''<!doctype html><html><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>Bridge settings · v0.6.8</title><style>body{font:16px system-ui;max-width:850px;margin:2em auto;padding:0 1em;background:#fafafa;color:#222}section{border:2px solid #398851;border-radius:6px;padding:1em}button{padding:.6em;margin:.3em}p{line-height:1.5}</style></head><body>
<h1>Bridge settings · v0.6.8</h1>''' + error + '''<section><h2>Settings backup / recovery</h2>
<p>''' + escape(summary) + '''</p><p>Valid configuration is saved automatically when the App starts.
The snapshot includes feed credentials. It stays in the host configuration folder if you keep that folder when uninstalling.
Density and range data are backed up separately.</p>
<button id="save" ''' + ('' if can_save else 'disabled') + '''>Save current settings</button>
<button id="restore" ''' + ('' if available else 'disabled') + '''>Restore saved settings</button>
<p id="result">Restoring replaces the App configuration in Home Assistant; restart the App afterward. Network port mappings and Home Assistant Home coordinates are not included.</p>
</section><p><a href="status-page">Bridge status</a> · <a href="./">Map</a></p><script>
for(const action of ['save','restore'])document.getElementById(action).addEventListener('click',async()=>{
 if(action==='restore'&&!confirm('Replace this App configuration with the saved settings? Restart the App afterward.'))return;
 const button=document.getElementById(action),out=document.getElementById('result');button.disabled=true;out.textContent='Working…';
 try{const r=await fetch('settings/'+action,{method:'POST',headers:{'Content-Type':'application/json','X-Bridge-Settings-Token':''' + json.dumps(TOKEN) + '''},body:JSON.stringify({confirmation:action.toUpperCase()})});const data=await r.json();if(!r.ok)throw new Error(data.error||'Operation failed');out.textContent=data.message;}catch(e){out.textContent=e.message;}finally{button.disabled=false;}
});</script></body></html>'''


def settings_post(handler, path):
    try:
        if handler.headers.get('Content-Type', '').split(';')[0].strip() != 'application/json':
            raise ValueError('Settings operations require application/json')
        if not secrets.compare_digest(handler.headers.get('X-Bridge-Settings-Token', ''), TOKEN):
            raise ValueError('Reload the settings page before making changes')
        length = int(handler.headers.get('Content-Length', '0'))
        if not 0 < length <= 1024:
            raise ValueError('Invalid settings request')
        data = json.loads(handler.rfile.read(length))
        action = path.removeprefix('/settings/')
        if action not in ('save', 'restore') or data.get('confirmation') != action.upper():
            raise ValueError('Explicit settings confirmation required')
        if action == 'save':
            save_snapshot()
            result = {'ok': True, 'message': 'Current settings saved in the persistent host folder.'}
        else:
            result = restore_snapshot()
        handler.send_json(result)
    except (ValueError, OSError, TypeError, AttributeError):
        # Do not expose credentials from malformed input or upstream errors.
        handler.send_json({'error': 'Settings operation failed. Reload the page and check the retained snapshot and Supervisor availability.'}, 400)
