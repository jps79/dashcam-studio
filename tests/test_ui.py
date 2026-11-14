import unittest
from PySide6.QtWidgets import QApplication
from PySide6.QtCore import QTimer
from dashcam_studio.app import Window


class UiTests(unittest.TestCase):
    def setUp(self):
        # Headless sandbox has no audio server; test video/timeline without it.
        from unittest.mock import patch
        import tempfile
        from PySide6.QtCore import QSettings
        settings_dir = tempfile.TemporaryDirectory()
        self.addCleanup(settings_dir.cleanup)
        settings = QSettings(settings_dir.name + "/settings.ini", QSettings.IniFormat)
        settings_patch = patch("dashcam_studio.app.QSettings", return_value=settings)
        settings_patch.start()
        self.addCleanup(settings_patch.stop)
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

    def test_kenwood_row_click_selects_and_imports(self):
        import tempfile
        import time
        from pathlib import Path

        from PySide6.QtCore import Qt
        from PySide6.QtTest import QTest
        from PySide6.QtWidgets import QDialogButtonBox, QListWidget
        from dashcam_studio.core import Project
        from dashcam_studio.kenwood import Clip

        app = QApplication.instance() or QApplication([])
        video = Path(__file__).resolve().parents[1] / 'demo/testvideo.mp4'
        with tempfile.TemporaryDirectory() as tmp:
            window = Window()
            window.set_project(Project.create(Path(tmp) / 'project'))
            selected = []

            def click_and_import():
                dialog = QApplication.activeModalWidget()
                listing = next(w for w in dialog.findChildren(QListWidget) if w.isVisible())
                button = dialog.findChild(QDialogButtonBox).button(QDialogButtonBox.Ok)
                selected.append(button.isEnabled())
                rect = listing.visualItemRect(listing.item(0))
                QTest.mouseClick(listing.viewport(), Qt.LeftButton, pos=rect.center())
                selected.append(button.isEnabled())
                button.click()
                if dialog.isVisible():
                    dialog.reject()

            QTimer.singleShot(0, click_and_import)
            window.choose_card_clips([Clip(video, 'MANUAL', None)])
            until = time.monotonic() + 10
            while window.busy and time.monotonic() < until:
                app.processEvents()
                time.sleep(.01)
            self.assertEqual(selected, [False, True])
            self.assertEqual(window.media.count(), 1)
            self.assertEqual(window.media.currentRow(), 0)
            self.assertTrue(window.player.source().isLocalFile())
            window.close()

    def test_recent_projects_persist_and_open_from_start_picker(self):
        import tempfile
        from pathlib import Path
        from PySide6.QtCore import QSettings
        from PySide6.QtWidgets import QListWidget, QPushButton
        from dashcam_studio.core import Project

        app = QApplication.instance() or QApplication([])
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            first = Window()
            first.settings = QSettings(str(root / 'settings.ini'), QSettings.IniFormat)
            project = Project.create(root / 'First')
            first.set_project(project)
            first.close()
            second = Window()
            second.settings = QSettings(str(root / 'settings.ini'), QSettings.IniFormat)
            self.assertEqual(second.recent_projects(), [str(project.root)])
            seen = []

            def open_recent():
                dialog = QApplication.activeModalWidget()
                listing = dialog.findChild(QListWidget)
                seen.append(listing.currentItem().text())
                button = next(b for b in dialog.findChildren(QPushButton)
                              if b.text() == 'Ausgewähltes öffnen')
                button.click()
                if dialog.isVisible():
                    dialog.reject()

            QTimer.singleShot(0, open_recent)
            second.show_project_picker()
            self.assertIn('First', seen[0])
            self.assertEqual(second.project.root, project.root)
            second.close()

    def test_project_deletion_requires_confirmation(self):
        import tempfile
        from pathlib import Path
        from unittest.mock import patch
        from PySide6.QtWidgets import QMessageBox
        from dashcam_studio.core import Project

        app = QApplication.instance() or QApplication([])
        with tempfile.TemporaryDirectory() as tmp:
            folder = Project.create(Path(tmp) / 'Testprojekt').root
            window = Window()
            with patch('dashcam_studio.app.QFile') as file, patch.object(
                    QMessageBox, 'question', return_value=QMessageBox.Cancel) as question:
                self.assertFalse(window.trash_recent_project(str(folder)))
                file.assert_not_called()
                self.assertIn('Alle darin gespeicherten Daten', question.call_args.args[2])
                question.return_value = QMessageBox.Yes
                file.return_value.moveToTrash.return_value = False
                with self.assertRaises(OSError):
                    window.trash_recent_project(str(folder))
                self.assertTrue(folder.exists())
                file.return_value.moveToTrash.return_value = True
                self.assertTrue(window.trash_recent_project(str(folder)))
            window.close()

    def test_theme_defaults_to_system_and_remembers_manual_choice(self):
        from PySide6.QtGui import QPalette

        app = QApplication.instance() or QApplication([])
        window = Window()
        self.assertEqual(window.theme_selector.currentData(), 'system')
        window.theme_selector.setCurrentIndex(window.theme_selector.findData('dark'))
        self.assertEqual(app.palette().color(QPalette.Window).name(), '#151b24')
        window.close()
        reopened = Window()
        self.assertEqual(reopened.theme_selector.currentData(), 'dark')
        reopened.theme_selector.setCurrentIndex(reopened.theme_selector.findData('light'))
        self.assertEqual(app.palette().color(QPalette.Window).name(), '#f3f5f8')
        reopened.theme_selector.setCurrentIndex(0)
        self.assertEqual(reopened.settings.value('appearance/theme'), 'system')
        reopened.close()

    def test_gnome_dark_preference_overrides_light_qt_palette(self):
        import os
        from unittest.mock import patch
        from PySide6.QtGui import QPalette

        app = QApplication.instance() or QApplication([])
        with patch.dict(os.environ, {'XDG_CURRENT_DESKTOP': 'GNOME'}), patch(
                'dashcam_studio.app.subprocess.check_output', return_value="'prefer-dark'\n"):
            window = Window()
            self.assertEqual(window.theme_selector.currentData(), 'system')
            self.assertEqual(app.palette().color(QPalette.Window).name(), '#151b24')
            window.theme_selector.setCurrentIndex(window.theme_selector.findData('light'))
            window.refresh_system_theme()
            self.assertEqual(app.palette().color(QPalette.Window).name(), '#f3f5f8')
            window.close()

    def test_playback_updates_keep_controls_in_place(self):
        app = QApplication.instance() or QApplication([])
        window = Window()
        window.show()
        app.processEvents()
        window.update_duration(42_000)
        window.telemetry_tracks = [
            ([0, 500], [{'speed_kmh': 123.4}, {}]),
            ([0, 500], [{'channels': [1.234, -2.345, 0.01]}, {}]),
        ]
        app.processEvents()
        before = [widget.geometry() for widget in (window.time, window.volume, window.monitors, window.video)]
        for pos in (0, 111, 500, 8_568, 11_576, 41_999):
            window.position(pos)
            app.processEvents()
            self.assertEqual(before, [widget.geometry() for widget in
                                      (window.time, window.volume, window.monitors, window.video)])
        window.close()

    def test_instruments_convert_speed_and_keep_gps_gaps(self):
        from dashcam_studio.instruments import display_speed

        app = QApplication.instance() or QApplication([])
        window = Window()
        gps = [{'ms': 0, 'speed_kmh': 80.4672}, {'ms': 500}, {'ms': 1000, 'speed_kmh': 80.4672}]
        accel = [{'ms': 500, 'channels': [0.1, -0.2, 0.9]}]
        window.instruments.set_tracks({'gps': gps, 'acceleration': accel}, 1500)
        window.telemetry_tracks = [([r['ms'] for r in rows], rows) for rows in (gps, accel)]
        window.speed_unit.setCurrentText('mph')
        window.position(0)
        self.assertAlmostEqual(display_speed(window.instruments.speed, 'mph'), 50)
        self.assertIn('50.0 mph', window.telemetry.text())
        path = window.instruments.paths[0]
        self.assertTrue(path.elementAt(2).isMoveTo())
        window.position(500)
        self.assertIsNone(window.instruments.speed)
        self.assertIn('+0.100', window.telemetry.text())
        self.assertEqual(window.settings.value('telemetry/unit'), 'mph')
        window.close()
