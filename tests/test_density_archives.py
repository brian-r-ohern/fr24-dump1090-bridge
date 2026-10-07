"""Archive staging, source boundaries and upgrade migration regression tests."""
import io
import json
import os
import sqlite3
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'fr24-dump1090'))
from traffic_density import DensityStore, cell_id
from density_archive import archive_file, geojson_file, restore_stream
from test_density_bridge import bridge

NOW = 1791309319.0

class SmallReads(io.BytesIO):
    def read(self, count=-1):
        if count < 0 or count > 65536:
            raise AssertionError('unbounded archive read')
        return super().read(min(count,7))

class DensityArchiveTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.store = DensityStore(Path(self.temp.name)/'sbs', clock=lambda:NOW, source_type='sbs_30003')
        self.ac = {'hex':'abc123','lat':43.1,'lon':-75.75,'alt_baro':37000}
        self.store.observe([self.ac])

    def tearDown(self):
        self.store.close()
        self.temp.cleanup()

    def encoded(self, payload):
        return json.dumps(payload,ensure_ascii=False).encode()

    def test_streamed_roundtrip_small_reads_and_identity(self):
        with archive_file(self.store) as path:
            data = path.read_bytes()
        self.assertEqual(json.loads(data)['source_type'],'sbs_30003')
        self.assertEqual(restore_stream(self.store,SmallReads(data),len(data))['retained'],1)
        self.assertFalse(any(p.name.startswith('.restore-') for p in self.store.directory.iterdir()))
        with archive_file(self.store,'2026-10') as path:
            self.assertEqual(json.loads(path.read_text())['months'],self.store.export()['months'])

    def test_source_mismatch_legacy_requires_attribution_and_full_validation(self):
        before = self.store.export()['months']
        payload = self.store.export()
        payload['source_type']='swim_tfms'
        data=self.encoded(payload)
        with self.assertRaisesRegex(ValueError,'source'):
            restore_stream(self.store,io.BytesIO(data),len(data))
        del payload['source_type'];data=self.encoded(payload)
        with self.assertRaisesRegex(ValueError,'explicitly confirm'):
            restore_stream(self.store,io.BytesIO(data),len(data))
        self.assertEqual(restore_stream(self.store,io.BytesIO(data),len(data),'sbs_30003')['retained'],1)
        payload['source_type']='sbs_30003'
        cell=payload['months']['2026-10'][0]
        cell['days']['2026-10-06']['observation_count']=100
        for data in (self.encoded(payload),self.encoded(self.store.export())+b'trailing'):
            with self.assertRaises(ValueError):
                restore_stream(self.store,io.BytesIO(data),len(data))
        self.assertEqual(self.store.export()['months'],before)
        # Repeated cells are detected on disk; validation cannot mutate a good preceding record.
        payload=self.store.export();payload['months']['2026-10']*=2;data=self.encoded(payload)
        with self.assertRaisesRegex(ValueError,'duplicate'):
            restore_stream(self.store,io.BytesIO(data),len(data))
        self.assertEqual(self.store.export()['months'],before)

    def test_stream_geojson_matches_query_including_uncertain_history(self):
        self.store.observe([{**self.ac,'lat':43.11,'hex':'abc124','alt_baro':700}], NOW+1)
        payload=self.store.export();payload['months']['2026-10'][0]['provenance']='another-origin'
        self.store.restore(payload)
        expected=self.store.geojson(zoom=14)
        with geojson_file(self.store,zoom=14) as path:
            actual=json.loads(path.read_text())
        self.assertEqual(actual['features'],expected['features'])
        self.assertEqual(actual['window'],expected['window'])
        self.assertFalse(actual['features'][0]['properties']['history_complete'])
        self.assertIsNone(actual['features'][0]['properties']['first_observed'])
        with self.assertRaises(ValueError):
            with geojson_file(self.store,zoom=18):pass

    def test_export_snapshot_survives_concurrent_new_observation(self):
        with archive_file(self.store) as path:
            self.store.observe([self.ac],NOW+1)
            count=json.loads(path.read_text())['months']['2026-10'][0]['days']['2026-10-06']['observation_count']
        self.assertEqual(count,1)
        self.assertEqual(self.store.query()['cells'][0]['observation_count'],2)

    def test_separate_sources_and_safe_legacy_migration(self):
        root=Path(self.temp.name)/'migration'
        old=DensityStore(root,clock=lambda:NOW)
        old.observe([self.ac]);old.close()
        before=(root/'2026-10.dat').read_bytes()
        with patch.dict(bridge.CFG,source='sbs_30003',density_legacy_source='unassigned'),patch.dict(os.environ,FR24_DENSITY_PATH=str(root)):
            with self.assertRaisesRegex(ValueError,'density_legacy_source'):
                bridge.open_density_store()
            self.assertEqual((root/'2026-10.dat').read_bytes(),before)
            bridge.CFG['density_legacy_source']='sbs_30003'
            migrated=bridge.open_density_store()
            try:
                self.assertEqual(migrated.export()['months']['2026-10'][0]['days']['2026-10-06']['observation_count'],1)
                bridge.CFG['source']='swim_tfms'
                faa=bridge.open_density_store()
                try:
                    self.assertEqual(faa.export()['months'],{})
                    faa.observe([self.ac],NOW)
                    self.assertEqual(faa.source_type,'swim_tfms')
                    self.assertEqual(migrated.export()['months']['2026-10'][0]['days']['2026-10-06']['observation_count'],1)
                finally:faa.close()
            finally:migrated.close()
        self.assertFalse((root/'2026-10.dat').exists())
        with self.assertRaisesRegex(ValueError,'different source'):
            DensityStore(root/'sbs_30003',clock=lambda:NOW,source_type='swim_tfms')

    def test_many_cell_archive_crosses_chunk_boundaries(self):
        db=self.store._db('2026-10')
        db.executemany('INSERT INTO daily VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)',
                       ((f'17/{10000+i}/34014','2026-10-06',1,1,0,0,1,0,37000.0,37000.0,NOW,NOW,1) for i in range(5000)))
        db.executemany('INSERT INTO origins VALUES (?,?)',((f'17/{10000+i}/34014',self.store.provenance) for i in range(5000)))
        self.store.flush(True)
        with archive_file(self.store) as path:
            self.assertGreater(path.stat().st_size,1024*1024)
            with path.open('rb') as file:
                self.assertEqual(restore_stream(self.store,file,path.stat().st_size)['retained'],5001)

    def test_large_upload_is_read_in_chunks_without_old_size_limit(self):
        # 257 MiB of whitespace exercises the HTTP-sized parser without storing
        # a giant test file or allocating a giant Python string.
        tail=self.encoded(self.store.export())
        class LargeUpload:
            padding=257*1024*1024
            maximum=0
            def read(self,count):
                self.maximum=max(self.maximum,count)
                if self.padding:
                    take=min(count,self.padding);self.padding-=take
                    return b' '*take
                return data.read(count)
        data=io.BytesIO(tail);stream=LargeUpload()
        result=restore_stream(self.store,stream,stream.padding+len(tail))
        self.assertEqual(result['retained'],1)
        self.assertLessEqual(stream.maximum,65536)

if __name__=='__main__':unittest.main()
