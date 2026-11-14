from pathlib import Path
import shutil
import tempfile
import unittest

from dashcam_studio.core import Project
from dashcam_studio.kenwood import parse, scan


def rmc(payload):
    checksum = 0
    for c in payload:
        checksum ^= ord(c)
    return f'${payload}*{checksum:02X}\n'.encode()


class KenwoodTests(unittest.TestCase):
    def test_parse_valid_fix_and_parking(self):
        valid = rmc('GPRMC,120000.00,A,4800.000,S,01100.000,W,10.0,,010126,,,A')
        invalid = rmc('GPRMC,,V,,,,,,,,,,N')
        raw = valid + b'$GSENS, 0.1,-0.2, 0.9\n' + invalid + b'$GSENS,0,0,1\n'
        data = parse(raw, 1000)
        self.assertAlmostEqual(data['gps'][0]['speed_kmh'], 18.52)
        self.assertEqual(data['gps'][0]['latitude'], -48)
        self.assertEqual(data['gps'][1], {'ms': 500, 'fix': False})
        self.assertEqual(data['acceleration'][1], {'ms': 500, 'channels': [0, 0, 1]})
        self.assertFalse(parse(valid[:-3] + b'zz\n', 500)['gps'][0]['fix'])

    def test_local_import_without_card(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            card = root / 'card'
            (card / 'NORMAL').mkdir(parents=True)
            (card / 'PARKING').mkdir()
            logs = card / 'SYSTEM/NMEA/NORMAL'
            logs.mkdir(parents=True)
            video = Path(__file__).resolve().parents[1] / 'demo/testvideo.mp4'
            for category in ('NORMAL', 'PARKING'):
                shutil.copyfile(video, card / category / 'clip.MOV')
            (card / 'NORMAL' / '._clip.MOV').write_bytes(b'AppleDouble')
            raw = rmc('GPRMC,,V,,,,,,,,,,N') + b'$GSENS,0,0,1\n'
            (logs / 'CLIP.nmea').write_bytes(raw)
            normal, parking = scan(card)
            self.assertEqual(normal.sidecar, logs / 'CLIP.nmea')
            self.assertIsNone(parking.sidecar)
            p = Project.create(root / 'project')
            item = p.import_media(normal.video, camera_clip=normal)
            other = p.import_media(parking.video, camera_clip=parking)
            shutil.rmtree(card)
            p = Project.open(p.root)
            self.assertTrue(p.path(item).is_file())
            self.assertEqual((p.root / 'telemetry' / (item['id'] + '.nmea')).read_bytes(), raw)
            self.assertEqual(p.load_telemetry(item)['acceleration'][0]['channels'], [0, 0, 1])
            self.assertIsNone(p.load_telemetry(other))

    def test_preview_and_recording_time(self):
        from datetime import datetime
        from dashcam_studio.kenwood import preview_image, recording_time

        self.assertEqual(recording_time('261110063946.MOV'), datetime(2026, 11, 10, 6, 39, 46))
        self.assertIsNone(recording_time('261131063946.MOV'))
        self.assertIsNone(recording_time('clip.MOV'))
        video = Path(__file__).resolve().parents[1] / 'demo/testvideo.mp4'
        self.assertTrue(preview_image(video).startswith(b'\x89PNG\r\n\x1a\n'))

    def test_photo_discovery_preview_and_copy(self):
        import subprocess
        from dashcam_studio.kenwood import preview_image

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            photos = root / 'card' / 'PICTURE'
            photos.mkdir(parents=True)
            photo = photos / '261110063946.JPG'
            subprocess.run(['ffmpeg', '-v', 'error', '-f', 'lavfi', '-i', 'color=size=128x72',
                            '-frames:v', '1', str(photo)], check=True)
            (photos / '._hidden.JPG').write_bytes(b'not a photo')
            clip, = scan(photos.parent)
            self.assertEqual((clip.category, clip.sidecar), ('PICTURE', None))
            self.assertTrue(preview_image(clip.video).startswith(b'\x89PNG'))
            project = Project.create(root / 'project')
            original = photo.read_bytes()
            copy = project.import_photo(photo)
            self.assertEqual(copy.parent, project.root / 'photos')
            self.assertEqual(copy.read_bytes(), original)
            self.assertEqual(project.import_photo(photo), copy)
            photo.write_bytes(original + b'changed')
            self.assertNotEqual(project.import_photo(photo), copy)
            self.assertEqual(copy.read_bytes(), original)

    def test_removal_persists_without_deleting_media(self):
        with tempfile.TemporaryDirectory() as tmp:
            source = Path(tmp)
            p = Project.create(source / 'project')
            jpg = source / 'sample.jpg'
            jpg.write_bytes(b'photo bytes')
            photo = p.import_photo(jpg)
            video = Path(__file__).resolve().parents[1] / 'demo/testvideo.mp4'
            item = p.import_media(video)
            path = p.path(item)
            p.remove_entry(photo=photo)
            p.remove_entry(media=item)
            p = Project.open(p.root)
            self.assertEqual(p.photos(), [])
            self.assertEqual(p.data['media'], [])
            self.assertTrue(path.is_file())
            self.assertTrue(video.is_file())
            self.assertEqual(photo.read_bytes(), jpg.read_bytes())
            p.import_photo(jpg)
            self.assertEqual(p.photos(), [photo])
