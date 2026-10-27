"""Qt UI; expensive I/O runs on one serialized worker, never on the GUI thread."""
import sys
import fcntl
from pathlib import Path
from concurrent.futures import ThreadPoolExecutor
from PySide6.QtCore import Qt, QUrl, QObject, Signal
from PySide6.QtGui import QShortcut, QKeySequence, QPixmap
from PySide6.QtWidgets import (QApplication, QMainWindow, QWidget, QVBoxLayout, QHBoxLayout,
    QPushButton, QLabel, QListWidget, QSlider, QFileDialog, QMessageBox, QCheckBox,
    QComboBox, QSplitter, QScrollArea, QDialog)
from PySide6.QtMultimedia import QMediaPlayer, QAudioOutput
from PySide6.QtMultimediaWidgets import QVideoWidget
from .core import Project
from .timeline import Filmstrip, timestamp


class Bridge(QObject):
    done = Signal(object, object)


class Fullscreen(QDialog):
    def __init__(self, parent, player, original, screen):
        super().__init__(parent)
        self.player, self.original = player, original
        self.setWindowTitle('DashCam Studio — Esc beendet Vollbild')
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        video = QVideoWidget(self)
        layout.addWidget(video)
        self.player.setVideoOutput(video)
        self.setGeometry(screen.geometry())
        self.show()
        self.windowHandle().setScreen(screen)
        self.showFullScreen()
        QShortcut(QKeySequence('Space'), self, activated=parent.toggle)
        QShortcut(QKeySequence('F11'), self, activated=self.close)

    def done(self, result):
        self.player.setVideoOutput(self.original)
        super().done(result)

    def closeEvent(self, event):
        self.player.setVideoOutput(self.original)
        super().closeEvent(event)


class Window(QMainWindow):
    def __init__(self):
        super().__init__()
        self.project = self.item = None
        self.project_lock = None
        self.full = None
        self.busy = False
        self.executor = ThreadPoolExecutor(max_workers=1)
        self.bridge = Bridge()
        self.bridge.done.connect(self.finished)
        self.setWindowTitle('DashCam Studio · 0.1')
        self.resize(1280, 850)
        root = QWidget()
        self.setCentralWidget(root)
        layout = QVBoxLayout(root)
        bar = QHBoxLayout()
        layout.addLayout(bar)
        self.actions = []
        for title, fn in [('Neues Projekt', self.new), ('Öffnen', self.open), ('Importieren', self.import_media),
                          ('Relink', self.relink), ('Proxy erstellen / nutzen', self.proxy), ('Export IN–OUT', self.export)]:
            button = QPushButton(title)
            button.clicked.connect(fn)
            bar.addWidget(button)
            self.actions.append(button)
        self.copy = QCheckBox('Ins Projekt kopieren')
        self.copy.setChecked(True)
        bar.addWidget(self.copy)
        splitter = QSplitter()
        layout.addWidget(splitter, 1)
        self.media = QListWidget()
        self.media.currentRowChanged.connect(self.select)
        splitter.addWidget(self.media)
        panel = QWidget()
        pv = QVBoxLayout(panel)
        self.video = QVideoWidget()
        pv.addWidget(self.video, 1)
        self.telemetry = QLabel('◯  — km/h    ·    Keine Geschwindigkeitsdaten\nG-Sensor    X —    Y —    Z —    ·    Keine Daten')
        self.telemetry.setMinimumHeight(70)
        pv.addWidget(self.telemetry)
        splitter.addWidget(panel)
        splitter.setSizes([250, 1000])
        self.player = QMediaPlayer(self)
        self.audio = QAudioOutput(self)
        self.player.setAudioOutput(self.audio)
        self.player.setVideoOutput(self.video)
        self.audio.setVolume(.7)
        self.player.errorOccurred.connect(lambda *_: self.statusBar().showMessage(self.player.errorString()))
        self.player.positionChanged.connect(self.position)
        self.player.durationChanged.connect(lambda duration: self.seek.setMaximum(duration))
        self.strip = Filmstrip()
        self.strip.seekRequested.connect(self.player.setPosition)
        layout.addWidget(self.strip)
        self.seek = QSlider(Qt.Horizontal)
        self.seek.sliderMoved.connect(self.player.setPosition)
        layout.addWidget(self.seek)
        controls = QHBoxLayout()
        layout.addLayout(controls)
        for text, fn in [('⏮', lambda: self.player.setPosition(0)), ('−5 s', lambda: self.jump(-5000)),
                         ('▶ / Ⅱ', self.toggle), ('Stop', self.player.stop), ('+5 s', lambda: self.jump(5000)),
                         ('IN [I]', lambda: self.marker('in_ms')), ('OUT [O]', lambda: self.marker('out_ms'))]:
            button = QPushButton(text)
            button.clicked.connect(fn)
            controls.addWidget(button)
        self.time = QLabel('00:00.000 / 00:00.000')
        controls.addWidget(self.time)
        self.volume = QSlider(Qt.Horizontal)
        self.volume.setRange(0, 100)
        self.volume.setValue(70)
        self.volume.setMaximumWidth(100)
        self.volume.valueChanged.connect(lambda n: self.audio.setVolume(n / 100))
        controls.addWidget(QLabel('Lautstärke'))
        controls.addWidget(self.volume)
        self.monitors = QComboBox()
        for screen in QApplication.screens():
            self.monitors.addItem(screen.name(), screen)
        controls.addWidget(self.monitors)
        full = QPushButton('Vollbild')
        full.clicked.connect(self.fullscreen)
        controls.addWidget(full)
        self.marks = QLabel('IN —   OUT —')
        layout.addWidget(self.marks)
        for key, fn in [('Space', self.toggle), ('I', lambda: self.marker('in_ms')),
                        ('O', lambda: self.marker('out_ms')), ('Left', lambda: self.jump(-5000)),
                        ('Right', lambda: self.jump(5000)), ('F11', self.fullscreen)]:
            QShortcut(QKeySequence(key), self, activated=fn)
        self.statusBar().showMessage('Projekt erstellen oder öffnen · Originalmedien bleiben unverändert')

    def job(self, fn, callback=lambda result: None):
        if self.busy:
            return
        self.busy = True
        self.media.setEnabled(False)
        for action in self.actions:
            action.setEnabled(False)
        self.statusBar().showMessage('Medien werden verarbeitet …')
        future = self.executor.submit(fn)
        future.add_done_callback(lambda f: self.bridge.done.emit(f, callback))

    def finished(self, future, callback):
        self.busy = False
        self.media.setEnabled(True)
        for action in self.actions:
            action.setEnabled(True)
        try:
            callback(future.result())
            self.statusBar().showMessage('Bereit')
        except Exception as error:
            QMessageBox.warning(self, 'DashCam Studio', str(error))
            self.statusBar().showMessage('Vorgang fehlgeschlagen')

    def guard(self, fn):
        try:
            fn()
        except Exception as error:
            QMessageBox.warning(self, 'Projekt', str(error))

    def new(self):
        folder = QFileDialog.getExistingDirectory(self, 'Leeren Projektordner wählen')
        if folder:
            self.guard(lambda: self.set_project(Project.create(folder)))

    def open(self):
        folder = QFileDialog.getExistingDirectory(self, 'Projektordner öffnen')
        if folder:
            self.guard(lambda: self.set_project(Project.open(folder)))

    def set_project(self, project):
        if self.project and self.project.root == project.root:
            return
        lock = (project.root / '.studio.lock').open('a')
        try:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            lock.close()
            raise ValueError('Dieses Projekt ist bereits in einer anderen Instanz geöffnet')
        if self.project_lock:
            self.project_lock.close()
        self.project_lock = lock
        self.player.stop()
        self.player.setSource(QUrl())
        self.project, self.item = project, None
        self.setWindowTitle(f'DashCam Studio · {project.root.name}')
        self.populate()

    def populate(self):
        self.media.clear()
        for item in self.project.data['media']:
            offline = not self.project.path(item).is_file()
            self.media.addItem(('⚠ OFFLINE · ' if offline else '') + item['name'])

    def import_media(self):
        if not self.project:
            return
        paths, _ = QFileDialog.getOpenFileNames(self, 'Videos importieren (Quellen nur lesend)')
        if paths:
            project, managed = self.project, self.copy.isChecked()
            def perform():
                errors = []
                for path in paths:
                    try:
                        project.import_media(path, managed)
                    except Exception as error:
                        errors.append(f'{Path(path).name}: {error}')
                return errors
            def completed(errors):
                self.populate()
                if errors:
                    QMessageBox.warning(self, 'Import', '\n'.join(errors))
            self.job(perform, completed)

    def select(self, index):
        self.player.stop()
        self.player.setSource(QUrl())
        self.item = None
        self.strip.set_media()
        if index < 0 or not self.project:
            return
        self.item = self.project.data['media'][index]
        self.update_marks()
        if not self.project.path(self.item).is_file():
            self.statusBar().showMessage('Medium offline · Datei über Relink wieder verbinden')
            return
        project, item = self.project, self.item
        def ready(paths):
            self.player.setSource(QUrl.fromLocalFile(str(project.path(item))))
            self.strip.set_media(paths, item['duration_ms'])
        self.job(lambda: project.thumbnails(item), ready)

    def relink(self):
        if not self.item:
            return
        path, _ = QFileDialog.getOpenFileName(self, 'Identische Mediendatei finden')
        if path:
            project, item = self.project, self.item
            self.job(lambda: project.relink(item, path), lambda _: self.populate())

    def proxy(self):
        if self.item:
            project, item = self.project, self.item
            self.job(lambda: project.proxy(item), lambda path: self.player.setSource(QUrl.fromLocalFile(path)))

    def export(self):
        if not self.item:
            return
        path, _ = QFileDialog.getSaveFileName(self, 'Neuen Export speichern', str(self.project.root / 'exports' / 'schnitt.mp4'), 'MP4 (*.mp4)')
        if path:
            project, item = self.project, self.item
            self.job(lambda: project.export(dict(item), path), lambda p: QMessageBox.information(self, 'Export fertig', p))

    def marker(self, key):
        if self.item and not self.busy and self.player.source().isValid():
            self.item[key] = min(self.player.position(), self.item['duration_ms'])
            self.guard(self.project.save)
            self.update_marks()

    def update_marks(self):
        item = self.item
        self.marks.setText(f'IN {item["in_ms"]/1000:.3f} s    OUT {item["out_ms"]/1000:.3f} s    ·    Export verwendet das Original')

    def toggle(self):
        if self.player.playbackState() == QMediaPlayer.PlaybackState.PlayingState:
            self.player.pause()
        else:
            self.player.play()

    def jump(self, delta):
        self.player.setPosition(max(0, min(self.player.duration(), self.player.position() + delta)))

    def position(self, value):
        if not self.seek.isSliderDown():
            self.seek.setValue(value)
        self.strip.set_position(value)
        self.time.setText(f'{timestamp(value)} / {timestamp(self.player.duration())}')

    def fullscreen(self):
        if self.full and self.full.isVisible():
            self.full.raise_()
            return
        self.full = Fullscreen(self, self.player, self.video, self.monitors.currentData() or QApplication.primaryScreen())

    def closeEvent(self, event):
        if self.busy:
            QMessageBox.information(self, 'Verarbeitung läuft', 'Bitte den laufenden Vorgang abwarten.')
            event.ignore()
            return
        self.player.stop()
        if self.full:
            self.full.close()
        if self.project_lock:
            self.project_lock.close()
        self.executor.shutdown(wait=False)
        super().closeEvent(event)


def main():
    app = QApplication(sys.argv)
    app.setStyle('Fusion')
    app.setStyleSheet('''QWidget { background:#151b24; color:#dde5ef; font-size:13px; }
        QPushButton, QComboBox { background:#263244; border:1px solid #3b4d65; padding:7px; border-radius:4px; }
        QPushButton:hover { background:#36516c; } QPushButton:disabled { color:#657185; }
        QListWidget { background:#10161e; padding:8px; } QListWidget::item:selected { background:#285b79; }
        QSlider::groove:horizontal { height:5px; background:#394657; }
        QSlider::handle:horizontal { background:#46b8dc; width:12px; margin:-5px 0; border-radius:5px; }
        QLabel { padding:4px; }''')
    window = Window()
    window.show()
    sys.exit(app.exec())


if __name__ == '__main__':
    main()
