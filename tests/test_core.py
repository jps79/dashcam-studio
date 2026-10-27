import json
from pathlib import Path
import subprocess
import tempfile
import unittest
from dashcam_studio.core import Project, fingerprint, probe


class MediaTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.source = self.root / 'test.mp4'
        subprocess.run(['ffmpeg', '-v', 'error', '-f', 'lavfi', '-i',
                        'testsrc2=size=320x180:rate=25', '-t', '2', '-c:v', 'libx264', str(self.source)], check=True)
        self.hash = fingerprint(self.source)
        self.project = Project.create(self.root / 'project')

    def tearDown(self):
        self.tmp.cleanup()

    def test_managed_roundtrip_cache_export(self):
        item = self.project.import_media(self.source)
        self.assertEqual(fingerprint(self.project.path(item)), self.hash)
        self.assertEqual(len(self.project.thumbnails(item)), 12)
        self.assertTrue(Path(self.project.proxy(item)).is_file())
        item.update(in_ms=400, out_ms=1400)
        self.project.save()
        reopened = Project.open(self.project.root)
        self.assertEqual(reopened.data['media'][0]['in_ms'], 400)
        output = self.root / 'cut.mp4'
        self.project.export(item, output)
        self.assertAlmostEqual(probe(output)['duration_ms'], 1000, delta=100)
        with self.assertRaises(ValueError):
            self.project.export(item, output)
        with self.assertRaises(ValueError):
            self.project.export(item, self.source)
        self.assertEqual(fingerprint(self.source), self.hash)

    def test_offline_relink(self):
        item = self.project.import_media(self.source, managed=False)
        moved = self.source.rename(self.root / 'moved.mp4')
        self.assertFalse(self.project.path(item).exists())
        wrong = self.root / 'wrong.mp4'
        wrong.write_bytes(b'wrong')
        with self.assertRaises(ValueError):
            self.project.relink(item, wrong)
        self.project.relink(item, moved)
        self.assertEqual(self.project.path(item), moved)

    def test_invalid_range_and_invalidation(self):
        item = self.project.import_media(self.source, managed=False)
        old = self.project.cache_dir(item)
        item.update(in_ms=1500, out_ms=500)
        with self.assertRaises(ValueError):
            self.project.export(item, self.root / 'bad.mp4')
        subprocess.run(['ffmpeg', '-v', 'error', '-y', '-f', 'lavfi', '-i',
                        'color=c=red:size=320x180:rate=25', '-t', '1', '-c:v', 'libx264', str(self.source)], check=True)
        self.project.refresh(item)
        self.assertNotEqual(old, self.project.cache_dir(item))
        self.assertEqual(item['in_ms'], 0)
        self.assertEqual(item['out_ms'], 1000)

    def test_path_traversal(self):
        item = self.project.import_media(self.source)
        item['path'] = '../test.mp4'
        with self.assertRaises(ValueError):
            self.project.path(item)


if __name__ == '__main__':
    unittest.main()
