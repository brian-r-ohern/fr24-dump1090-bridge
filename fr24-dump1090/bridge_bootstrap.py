"""Start collection with valid options, or expose an explicit recovery page."""
import json
import signal
import sys
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

from bridge_settings import checked_options, read_options, save_snapshot, settings_page, settings_post


class RecoveryHandler(BaseHTTPRequestHandler):
    def log_message(self, *_args):
        pass

    def send_json(self, payload, code=200):
        self._send(json.dumps(payload).encode(), 'application/json', code)

    def _send(self, body, content_type, code=200):
        self.send_response(code)
        self.send_header('Content-Type', content_type)
        self.send_header('Content-Length', str(len(body)))
        self.send_header('Cache-Control', 'no-store')
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        path = self.path.partition('?')[0]
        if path == '/health':
            self.send_json({'service_status': 'ok', 'mode': 'settings_recovery', 'feed_status': 'not_configured'})
        elif path == '/status':
            self.send_json({'build_version': '0.6.8', 'service_status': 'ok', 'mode': 'settings_recovery', 'feed_status': 'not_configured'})
        elif path in ('/', '/settings', '/status-page'):
            self._send(settings_page(recovery_error=True).encode(), 'text/html; charset=utf-8')
        else:
            self.send_json({'error': 'Configure or restore settings, then restart the App'}, 503)

    def do_POST(self):
        settings_post(self, self.path.partition('?')[0])


def main():
    try:
        checked_options(read_options())
    except (ValueError, OSError, TypeError):
        print('[INFO] Feed settings are incomplete or invalid. Serving settings recovery on port 8085; collection is paused.', flush=True)
        signal.signal(signal.SIGTERM, lambda *_args: sys.exit(0))
        ThreadingHTTPServer(('0.0.0.0', 8085), RecoveryHandler).serve_forever()
        return
    try:
        save_snapshot()
        print('[INFO] Persistent settings snapshot saved or already current.', flush=True)
    except (ValueError, OSError, TypeError, AttributeError):
        print('[WARN] Persistent settings snapshot unavailable or unreadable; collection will continue. Existing snapshot preserved.', flush=True)
    import fr24_dump1090
    fr24_dump1090.main()


if __name__ == '__main__':
    main()
