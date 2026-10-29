"""Disk retention for locally observed routes; live history stays bounded in RAM."""
import json
import sqlite3
from pathlib import Path
from airport_context import distance_nm

DAY = 86400

class LocalHistory:
    def __init__(self, directory, source):
        directory=Path(directory);directory.mkdir(parents=True,exist_ok=True)
        self.path=directory/(source+'.sqlite3')
        with self.connect() as db:
            db.executescript('CREATE TABLE IF NOT EXISTS tracks (key TEXT PRIMARY KEY, identity TEXT, updated REAL); CREATE TABLE IF NOT EXISTS samples (key TEXT,t REAL,body TEXT,PRIMARY KEY(key,t)); CREATE INDEX IF NOT EXISTS sample_time ON samples(t);')
    def connect(self):
        db=sqlite3.connect(self.path,timeout=5)
        db.execute('PRAGMA journal_mode=WAL')
        return db
    def retain(self, tracks, now, airports, covered):
        """Both route airports covered and a position within 10 NM of either endpoint."""
        db=self.connect()
        try:
            with db:
                db.execute('DELETE FROM samples WHERE t<?',(now-DAY,))
                db.execute('DELETE FROM tracks WHERE updated<?',(now-DAY,))
                for key,track in tracks.items():
                    identity=track['identity'];points=track['samples']
                    if not points:continue
                    origin=str(identity.get('route_origin') or identity.get('origin') or '').upper()
                    dest=str(identity.get('route_destination') or identity.get('destination') or '').upper()
                    codes=airports.lookup_many([origin,dest]) if origin and dest else {}
                    a,b=codes.get(origin),codes.get(dest)
                    qualified=bool(a and b and covered(a) and covered(b) and any(distance_nm(p,a)<=10 or distance_nm(p,b)<=10 for p in points))
                    exists=db.execute('SELECT identity FROM tracks WHERE key=?',(key,)).fetchone()
                    if exists:
                        previous=json.loads(exists[0])
                        changed=any(previous.get(k) and identity.get(k) and previous[k]!=identity[k] for k in ('flight','route_origin','route_destination'))
                        if changed:
                            db.execute('DELETE FROM samples WHERE key=?',(key,))
                            db.execute('DELETE FROM tracks WHERE key=?',(key,))
                            exists=None
                    if not qualified and not exists:continue
                    db.execute('INSERT OR REPLACE INTO tracks VALUES(?,?,?)',(key,json.dumps(identity),points[-1]['t']))
                    # Backfill the rolling hour on first qualification, then only new observations.
                    last=db.execute('SELECT max(t) FROM samples WHERE key=?',(key,)).fetchone()[0]
                    rows=[p for p in points if last is None or p['t']>=last]
                    db.executemany('INSERT OR REPLACE INTO samples VALUES(?,?,?)',[(key,p['t'],json.dumps(p,separators=(',',':'),allow_nan=False)) for p in rows])
        finally:db.close()
    def snapshot(self, now, keys=None):
        db=self.connect();out={}
        try:
            for key,identity in db.execute('SELECT key,identity FROM tracks WHERE updated>=?',(now-DAY,)):
                if keys is not None and key not in keys:continue
                samples=[json.loads(r[0]) for r in db.execute('SELECT body FROM samples WHERE key=? AND t>=? ORDER BY t',(key,now-DAY))]
                if samples:out[key]={'identity':json.loads(identity),'samples':samples,'retention':'local_route_24h'}
        finally:db.close()
        return out
