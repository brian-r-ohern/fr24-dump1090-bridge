"""Bounded, volatile aircraft-feed activity; not a TCP connection counter."""
import hashlib
import re
import threading
import time
from datetime import datetime, timezone

class FeedConsumers:
    def __init__(self, window=60, limit=256, clock=time.monotonic, wall_clock=time.time):
        self.window, self.limit, self.clock, self.wall_clock = window, limit, clock, wall_clock
        self.lock = threading.Lock()
        self.clients = {}

    def _prune(self, now):
        self.clients = {k:v for k,v in self.clients.items() if now-v['seen'] < self.window}

    def record(self, address, user_agent='', client_id=''):
        # Deliberately do not retain addresses, user agents, arbitrary query strings or headers.
        explicit = client_id if re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9_.-]{0,47}', client_id or '') else ''
        identity = ('named', explicit) if explicit else ('fallback', address, user_agent[:256])
        key = hashlib.sha256(repr(identity).encode()).hexdigest()[:16]
        now = self.clock()
        with self.lock:
            self._prune(now)
            if key not in self.clients and len(self.clients) >= self.limit:
                del self.clients[min(self.clients, key=lambda k:self.clients[k]['seen'])]
            row = self.clients.setdefault(key, {'seen':now, 'first':now, 'requests':0,
                'label': 'Built-in Bridge map' if explicit=='bridge-map' else (explicit or 'Unidentified client '+key[:6]),
                'internal':explicit=='bridge-map', 'identification':'self-reported' if explicit else 'address/user-agent estimate'})
            row.update(seen=now, wall=self.wall_clock(), requests=row['requests']+1)

    def snapshot(self):
        now=self.clock()
        with self.lock:
            self._prune(now)
            rows=[{'id':k, 'label':v['label'], 'internal':v['internal'], 'identification':v['identification'],
                'last_seen':datetime.fromtimestamp(v['wall'],timezone.utc).isoformat(),
                'last_seen_age_seconds':round(max(0,now-v['seen']),1), 'requests_in_activity_session':v['requests'],
                'mean_poll_interval_seconds':round((v['seen']-v['first'])/(v['requests']-1),2) if v['requests']>1 else None}
                for k,v in sorted(self.clients.items())]
        return {'window_seconds':self.window, 'recent_count':len(rows),
                'external_count':sum(not r['internal'] for r in rows), 'internal_count':sum(r['internal'] for r in rows),
                'count_is_estimate':any(r['identification']=='address/user-agent estimate' for r in rows),
                'capacity':self.limit, 'clients':rows}
