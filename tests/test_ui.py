import unittest
from PySide6.QtWidgets import QApplication
from PySide6.QtCore import QTimer
from dashcam_studio.app import Window


class UiTests(unittest.TestCase):
    def setUp(self):
        # Headless sandbox has no audio server; test video/timeline without it.
        from unittest.mock import patch
        self.audio_factory = patch('dashcam_studio.app.QAudioOutput')
        self.audio_sink = patch('dashcam_studio.app.QMediaPlayer.setAudioOutput')
        self.audio_factory.start()
        self.audio_sink.start()
        self.addCleanup(self.audio_factory.stop)
        self.addCleanup(self.audio_sink.stop)

    def test_window(self):
        app = QApplication.instance() or QApplication([])
        window = Window()
        window.show()
        app.processEvents()
        self.assertEqual(window.volume.value(), 70)
        self.assertTrue(window.copy.isChecked())
        self.assertIn('Keine Daten', window.telemetry.text())
        window.close()
        app.processEvents()

    def test_media_workflow(self):
        import tempfile
        import time
        from pathlib import Path
        from dashcam_studio.core import Project
        app = QApplication.instance() or QApplication([])
        with tempfile.TemporaryDirectory() as folder:
            project = Project.create(Path(folder) / 'project')
            project.import_media(Path(__file__).resolve().parents[1] / 'demo' / 'testvideo.mp4')
            window = Window()
            window.set_project(project)
            window.show()
            window.media.setCurrentRow(0)
            deadline = time.monotonic() + 15
            while window.busy and time.monotonic() < deadline:
                app.processEvents()
                time.sleep(.01)
            self.assertFalse(window.busy)
            self.assertEqual(len(window.strip.frames), 12)
            self.assertTrue(window.player.source().isLocalFile())
            deadline = time.monotonic() + 5
            while not window.player.duration() and time.monotonic() < deadline:
                app.processEvents()
                time.sleep(.01)
            self.assertGreater(window.player.duration(), 0)
            window.player.setPosition(1000)
            window.marker('in_ms')
            self.assertEqual(project.data['media'][0]['in_ms'], 1000)
            app.processEvents()
            self.assertEqual(window.strip.position, window.player.position())
            self.assertIn('00:01.000', window.time.text())
            window.strip.seekRequested.emit(2500)
            app.processEvents()
            self.assertEqual(window.player.position(), 2500)
            self.assertEqual(window.strip.position, 2500)
            window.close()
            app.processEvents()


    def test_timeline_mapping(self):
        from dashcam_studio.timeline import Filmstrip, timestamp
        from PySide6.QtCore import Qt, QPoint
        from PySide6.QtTest import QTest
        app = QApplication.instance() or QApplication([])
        strip = Filmstrip()
        strip.resize(1001, 115)
        strip.set_media(duration=30000)
        strip.show()
        app.processEvents()
        self.assertEqual(strip.time_at(0), 0)
        self.assertEqual(strip.time_at(500), 15000)
        self.assertEqual(strip.time_at(1000), 30000)
        seen = []
        strip.seekRequested.connect(seen.append)
        QTest.mouseClick(strip, Qt.LeftButton, pos=QPoint(275, 40))
        self.assertEqual(seen, [8250])
        strip.set_position(8240)
        self.assertEqual(strip.position, 8240)
        self.assertEqual(timestamp(8240), '00:08.240')
        strip.resize(2001, 115)
        self.assertEqual(strip.time_at(1000), 15000)
        strip.set_media()
        self.assertEqual(strip.position, 0)
        self.assertFalse(strip.frames)
        strip.close()
