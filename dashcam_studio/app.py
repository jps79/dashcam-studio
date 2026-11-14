"""Qt UI; expensive I/O runs on one serialized worker, never on the GUI thread."""
import sys
import os
import subprocess
from bisect import bisect_right
import fcntl
from pathlib import Path
from concurrent.futures import ThreadPoolExecutor
from PySide6.QtCore import Qt, QUrl, QObject, Signal, QSize, QTimer, QCoreApplication, QEvent, QSettings, QFile
from PySide6.QtGui import QShortcut, QKeySequence, QPixmap, QIcon, QImageReader, QPalette, QColor, QFontDatabase
from PySide6.QtWidgets import (QApplication, QMainWindow, QWidget, QVBoxLayout, QHBoxLayout,
    QPushButton, QLabel, QListWidget, QSlider, QFileDialog, QMessageBox, QCheckBox,
    QComboBox, QSplitter, QScrollArea, QDialog, QDialogButtonBox, QListWidgetItem, QTabWidget, QStyledItemDelegate, QMenu, QSizePolicy, QColorDialog)
from PySide6.QtMultimedia import QMediaPlayer, QAudioOutput
from PySide6.QtMultimediaWidgets import QVideoWidget
from .core import Project
from .kenwood import CATEGORIES, preview_image, recording_time, scan
from .instruments import DEFAULT_COLORS, Instruments, display_speed
from .timeline import Filmstrip, timestamp


THEMES = ('system', 'light', 'dark')


def system_theme(app):
    # GNOME can report prefer-dark while Qt Fusion still has a light palette.
    if 'GNOME' in os.environ.get('XDG_CURRENT_DESKTOP', '').upper().split(':'):
        try:
            setting = subprocess.check_output(
                ['gsettings', 'get', 'org.gnome.desktop.interface', 'color-scheme'],
                stderr=subprocess.DEVNULL, text=True, timeout=0.5).strip().strip("'")
        except (OSError, subprocess.SubprocessError):
            setting = None
        if setting in ('prefer-dark', 'prefer-light'):
            return setting.removeprefix('prefer-')
    return {Qt.ColorScheme.Dark: 'dark', Qt.ColorScheme.Light: 'light'}.get(
        app.styleHints().colorScheme())


def apply_theme(app, mode):
    if mode == 'system':
        mode = system_theme(app)
        if mode is None:
            app.setPalette(QPalette())
            return
    colors = (
        ('#151b24', '#10161e', '#263244', '#dde5ef', '#8593a5', '#285b79', '#ffffff')
        if mode == 'dark' else
        ('#f3f5f8', '#ffffff', '#e5eaf0', '#202a36', '#687583', '#17618e', '#ffffff')
    )
    window, base, button, text, muted, accent, selected = map(QColor, colors)
    palette = QPalette()
    for role, color in {
        QPalette.Window: window, QPalette.Base: base, QPalette.AlternateBase: button,
        QPalette.Button: button, QPalette.WindowText: text, QPalette.Text: text,
        QPalette.ButtonText: text, QPalette.ToolTipBase: base, QPalette.ToolTipText: text,
        QPalette.Highlight: accent, QPalette.HighlightedText: selected,
    }.items():
        palette.setColor(role, color)
    for role in (QPalette.WindowText, QPalette.Text, QPalette.ButtonText):
        palette.setColor(QPalette.Disabled, role, muted)
    app.setPalette(palette)


class MediaList(QListWidget):
    def mousePressEvent(self, event):
        # A context click should not load another clip just to show its menu.
        if event.button() == Qt.RightButton:
            event.accept()
            return
        super().mousePressEvent(event)


class CheckOnRowClick(QStyledItemDelegate):
    """Let the list handle mouse toggles once, even on the checkbox."""
    def editorEvent(self, event, model, option, index):
        if event.type() in (QEvent.MouseButtonPress, QEvent.MouseButtonRelease,
                            QEvent.MouseButtonDblClick):
            return False
        return super().editorEvent(event, model, option, index)


def toggle_checked(item):
    item.setCheckState(Qt.Unchecked if item.checkState() == Qt.Checked else Qt.Checked)


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


NO_TELEMETRY = "— km/h · Keine GPS-Daten\nG-Sensor · Keine Daten"


class Window(QMainWindow):
    def __init__(self):
        super().__init__()
        self.project = self.item = None
        self.settings = QSettings("DashCam Studio", "DashCam Studio")
        self.telemetry_tracks = []
        self.photo_rows = []
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
                          ('Kenwood-SD importieren', self.import_card), ('Entfernen', self.remove_selected), ('Relink', self.relink), ('Proxy erstellen / nutzen', self.proxy), ('Export IN–OUT', self.export)]:
            button = QPushButton(title)
            button.clicked.connect(fn)
            bar.addWidget(button)
            self.actions.append(button)
        self.copy = QCheckBox('Ins Projekt kopieren')
        self.copy.setChecked(True)
        bar.addWidget(self.copy)
        theme = QComboBox()
        theme.setAccessibleName('Farbschema')
        for label, mode in zip(('System', 'Hell', 'Dunkel'), THEMES):
            theme.addItem(label, mode)
        theme.setCurrentIndex(max(0, theme.findData(self.settings.value('appearance/theme', 'system'))))
        theme.currentIndexChanged.connect(lambda _: self.set_theme(theme.currentData()))
        self.theme_selector = theme
        self.set_theme(theme.currentData(), remember=False)
        QApplication.instance().styleHints().colorSchemeChanged.connect(self.refresh_system_theme)
        appearance = QHBoxLayout()
        appearance.addStretch()
        appearance.addWidget(QLabel('Farbschema:'))
        appearance.addWidget(theme)
        layout.addLayout(appearance)
        splitter = QSplitter()
        layout.addWidget(splitter, 1)
        self.media = MediaList()
        self.media.setContextMenuPolicy(Qt.CustomContextMenu)
        self.media.customContextMenuRequested.connect(self.media_context_menu)
        self.media.currentRowChanged.connect(self.select)
        splitter.addWidget(self.media)
        panel = QWidget()
        pv = QVBoxLayout(panel)
        self.video = QVideoWidget()
        pv.addWidget(self.video, 1)
        self.photo_view = QLabel(alignment=Qt.AlignCenter)
        self.photo_view.hide()
        pv.addWidget(self.photo_view, 1)
        self.telemetry = QLabel('◯  — km/h    ·    Keine Geschwindigkeitsdaten\nG-Sensor    X —    Y —    Z —    ·    Keine Daten')
        self.telemetry.setSizePolicy(QSizePolicy.Ignored, QSizePolicy.Fixed)
        self.telemetry.setFixedHeight(44)
        pv.addWidget(self.telemetry)
        self.instruments = Instruments()
        settings_row = QHBoxLayout()
        pv.addLayout(settings_row)
        self.speed_unit = QComboBox()
        self.speed_unit.addItems(['km/h', 'mph'])
        self.speed_unit.setCurrentText(self.settings.value('telemetry/unit', 'km/h'))
        self.instruments.unit = self.speed_unit.currentText()
        self.speed_unit.currentTextChanged.connect(self.change_speed_unit)
        settings_row.addWidget(QLabel('Tacho-Einheit:'))
        settings_row.addWidget(self.speed_unit)
        for index, (label, default) in enumerate(zip(('GPS', 'Kanal 1', 'Kanal 2', 'Kanal 3'), DEFAULT_COLORS)):
            color = QColor(self.settings.value(f'telemetry/color{index}', default))
            self.instruments.colors[index] = color if color.isValid() else QColor(default)
            button = QPushButton()
            self.update_color_button(button, label, index)
            button.clicked.connect(lambda checked=False, i=index, name=label, b=button:
                                   self.choose_line_color(i, name, b))
            settings_row.addWidget(button)
        settings_row.addStretch()
        pv.addWidget(self.instruments)
        splitter.addWidget(panel)
        splitter.setSizes([250, 1000])
        self.player = QMediaPlayer(self)
        self.audio = QAudioOutput(self)
        self.player.setAudioOutput(self.audio)
        self.player.setVideoOutput(self.video)
        self.audio.setVolume(.7)
        self.player.errorOccurred.connect(lambda *_: self.statusBar().showMessage(self.player.errorString()))
        self.player.positionChanged.connect(self.position)
        self.player.durationChanged.connect(self.update_duration)
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
        self.time.setFont(QFontDatabase.systemFont(QFontDatabase.FixedFont))
        self.time.setAlignment(Qt.AlignCenter)
        self.reserve_time_width(0)
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
            result = future.result()
            self.statusBar().showMessage('Bereit')
            callback(result)
        except Exception as error:
            QMessageBox.warning(self, 'DashCam Studio', str(error))
            self.statusBar().showMessage('Vorgang fehlgeschlagen')

    def guard(self, fn):
        try:
            fn()
        except Exception as error:
            QMessageBox.warning(self, 'Projekt', str(error))

    def refresh_system_theme(self):
        if self.theme_selector.currentData() == 'system':
            self.set_theme('system', remember=False)

    def set_theme(self, mode, *, remember=True):
        apply_theme(QApplication.instance(), mode)
        if remember:
            self.settings.setValue('appearance/theme', mode)
            self.settings.sync()

    def recent_projects(self):
        return self.settings.value('projects/recent', [], type=list)

    def show_project_picker(self):
        dialog = QDialog(self)
        dialog.setWindowTitle('DashCam Studio · Projekt auswählen')
        dialog.resize(650, 330)
        layout = QVBoxLayout(dialog)
        layout.addWidget(QLabel('Zuletzt verwendete Projekte'))
        listing = QListWidget()
        layout.addWidget(listing)
        for path in self.recent_projects():
            folder = Path(path)
            entry = QListWidgetItem(f'{folder.name}\n{folder}')
            entry.setData(Qt.UserRole, path)
            listing.addItem(entry)
        if not listing.count():
            layout.addWidget(QLabel('Noch keine zuletzt verwendeten Projekte gespeichert.'))
        buttons = QDialogButtonBox(QDialogButtonBox.Cancel)
        buttons.button(QDialogButtonBox.Cancel).setText('Schließen')
        recent = buttons.addButton('Ausgewähltes öffnen', QDialogButtonBox.ActionRole)
        other = buttons.addButton('Anderes Projekt öffnen …', QDialogButtonBox.ActionRole)
        new = buttons.addButton('Neues Projekt …', QDialogButtonBox.ActionRole)
        management = QHBoxLayout()
        forget = QPushButton('Aus Liste entfernen')
        delete = QPushButton('Projekt löschen …')
        management.addWidget(forget)
        management.addWidget(delete)
        management.addStretch()
        layout.addLayout(management)

        def update_actions(entry):
            for button in (recent, forget, delete):
                button.setEnabled(entry is not None)

        def remove_entry(*, delete_project=False):
            entry = listing.currentItem()
            if entry is None:
                return
            path = entry.data(Qt.UserRole)
            if delete_project:
                try:
                    if not self.trash_recent_project(path):
                        return
                except (OSError, ValueError, KeyError) as error:
                    QMessageBox.warning(dialog, 'Projekt löschen', str(error))
                    return
            self.settings.setValue('projects/recent', [p for p in self.recent_projects() if p != path])
            self.settings.sync()
            listing.takeItem(listing.row(entry))

        update_actions(None)
        listing.currentItemChanged.connect(lambda entry, _: update_actions(entry))
        forget.clicked.connect(lambda: remove_entry())
        delete.clicked.connect(lambda: remove_entry(delete_project=True))

        def open_entry(entry):
            if entry:
                self.guard(lambda: self.set_project(Project.open(entry.data(Qt.UserRole))))
                if self.project:
                    dialog.accept()

        def use_picker(callback):
            callback()
            if self.project:
                dialog.accept()

        listing.itemDoubleClicked.connect(open_entry)
        recent.clicked.connect(lambda: open_entry(listing.currentItem()))
        other.clicked.connect(lambda: use_picker(self.open))
        new.clicked.connect(lambda: use_picker(self.new))
        buttons.rejected.connect(dialog.reject)
        layout.addWidget(buttons)
        if listing.count():
            listing.setCurrentRow(0)
            recent.setDefault(True)
        dialog.exec()

    def trash_recent_project(self, path):
        folder = Path(path)
        if not folder.is_absolute() or folder.resolve() != folder or folder in (Path.home(), Path('/')):
            raise ValueError('Dieser Projektpfad kann nicht gelöscht werden.')
        if self.project and self.project.root == folder:
            raise ValueError('Das aktuell geöffnete Projekt kann nicht gelöscht werden.')
        Project.open(folder)
        answer = QMessageBox.question(
            self, 'Gesamtes Projekt löschen?',
            f'Der gesamte Projektordner wird aus seinem bisherigen Speicherort entfernt:\n{folder}\n\n'
            'Alle darin gespeicherten Daten werden in den Papierkorb verschoben, '
            'einschließlich Videos, Fotos, Telemetrie und Exporten. '
            'Dateien außerhalb des Projektordners bleiben erhalten.',
            QMessageBox.Yes | QMessageBox.Cancel, QMessageBox.Cancel)
        if answer != QMessageBox.Yes:
            return
        with (folder / '.studio.lock').open('a') as lock:
            try:
                fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
            except BlockingIOError as error:
                raise ValueError('Das Projekt ist in einer anderen Instanz geöffnet.') from error
            if not QFile(str(folder)).moveToTrash():
                raise OSError('Der Projektordner konnte nicht in den Papierkorb verschoben werden.')
        return True

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
        path = str(project.root)
        recent = [entry for entry in self.recent_projects() if entry != path]
        self.settings.setValue('projects/recent', [path, *recent][:10])
        self.settings.sync()

    def populate(self):
        self.media.clear()
        for item in self.project.data['media']:
            offline = not self.project.path(item).is_file()
            self.media.addItem(('⚠ OFFLINE · ' if offline else '') + item['name'])

        self.photo_rows = self.project.photos()
        for photo in self.photo_rows:
            self.media.addItem(f'Foto · {photo.name}')

    def media_context_menu(self, pos):
        entry = self.media.itemAt(pos)
        if entry is None or self.busy:
            return
        row = self.media.row(entry)
        menu = QMenu(self.media)
        open_action = menu.addAction('Anzeigen')
        remove_action = menu.addAction('Aus Projektliste entfernen')
        action = menu.exec(self.media.viewport().mapToGlobal(pos))
        if action == open_action:
            self.media.setCurrentRow(row)
        elif action == remove_action:
            self.remove_row(row)
        menu.deleteLater()

    def remove_selected(self):
        self.remove_row(self.media.currentRow())

    def remove_row(self, row):
        if not self.project or self.busy or not 0 <= row < self.media.count():
            return
        project = self.project
        count = len(project.data['media'])
        media = project.data['media'][row] if row < count else None
        photo = self.photo_rows[row - count] if row >= count else None

        def remove():
            project.remove_entry(media=media, photo=photo)
            self.populate()
            self.statusBar().showMessage('Aus der Projektliste entfernt. Dateien bleiben erhalten.')

        self.guard(remove)

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

    def import_card(self):
        if not self.project:
            self.statusBar().showMessage('Bitte zuerst ein Projekt öffnen oder erstellen')
            return
        root = QFileDialog.getExistingDirectory(self, 'Hauptordner der Kenwood-SD-Karte wählen')
        if root:
            self.job(lambda: scan(root), self.choose_card_clips)

    def choose_card_clips(self, clips):
        if not clips:
            QMessageBox.information(self, 'Kenwood-SD', 'Keine Videos oder Fotos in den Kenwood-Ordnern gefunden.')
            return
        dialog = QDialog(self)
        dialog.setWindowTitle('Kenwood-Aufnahmen auswählen')
        dialog.resize(710, 570)
        layout = QVBoxLayout(dialog)
        layout.addWidget(QLabel('Videos und Telemetrie werden ins Projekt kopiert, Fotos in den Ordner „photos“.'))
        layout.addWidget(QLabel('Datum und Uhrzeit aus dem Kameradateinamen (Kamerauhr).'))
        layout.addWidget(QLabel('Klicke auf ein Vorschaubild oder eine Zeile, um sie zum Import zu markieren.'))
        tabs = QTabWidget(dialog)
        layout.addWidget(tabs)
        labels = {
            'MANUAL': QCoreApplication.translate('KenwoodImport', 'Manuelle Aufnahmen'),
            'NORMAL': QCoreApplication.translate('KenwoodImport', 'Normale Aufnahmen'),
            'EVENT': QCoreApplication.translate('KenwoodImport', 'Ereignisaufnahmen'),
            'PARKING': QCoreApplication.translate('KenwoodImport', 'Parkaufnahmen'),
            'PICTURE': QCoreApplication.translate('KenwoodImport', 'Fotos'),
        }
        entries = {}
        placeholder = QPixmap(128, 72)
        placeholder.fill(Qt.GlobalColor.darkGray)
        for category in CATEGORIES:
            dated = [(recording_time(clip.video), clip) for clip in clips if clip.category == category]
            dated.sort(key=lambda row: (row[0] is not None, row[0]), reverse=True)
            listing = QListWidget()
            listing.setIconSize(QSize(128, 72))
            listing.setItemDelegate(CheckOnRowClick(listing))
            listing.itemClicked.connect(toggle_checked)
            tabs.addTab(listing, f'{labels[category]} ({len(dated)})')
            entries[listing] = []
            for recorded, clip in dated:
                when = recorded.strftime('%d.%m.%Y · %H:%M:%S') if recorded else 'Aufnahmezeit unbekannt'
                detail = 'JPEG-Foto' if category == 'PICTURE' else (
                    'NMEA vorhanden' if clip.sidecar else 'ohne NMEA')
                entry = QListWidgetItem(QIcon(placeholder), f'{when}\n{clip.video.name} · {detail}')
                entry.setSizeHint(QSize(0, 80))
                entry.setCheckState(Qt.Unchecked)
                listing.addItem(entry)
                entries[listing].append((entry, clip))

        # One frame at a time, prioritizing only rows currently on screen.
        # The worker returns bytes; Qt objects stay on the GUI thread.
        preview_worker = ThreadPoolExecutor(max_workers=1)
        pending = None
        attempted = set()
        timer = QTimer(dialog)

        def update_previews():
            nonlocal pending
            if pending is not None:
                entry, future = pending
                if not future.done():
                    return
                pixmap = QPixmap()
                if pixmap.loadFromData(future.result()):
                    entry.setIcon(QIcon(pixmap))
                pending = None
            listing = tabs.currentWidget()
            viewport = listing.viewport().rect()
            for entry, clip in entries[listing]:
                if clip.video not in attempted and listing.visualItemRect(entry).intersects(viewport):
                    attempted.add(clip.video)
                    pending = entry, preview_worker.submit(preview_image, clip.video)
                    break

        timer.timeout.connect(update_previews)
        buttons = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        import_button = buttons.button(QDialogButtonBox.Ok)
        buttons.button(QDialogButtonBox.Cancel).setText('Abbrechen')

        def selected_clips():
            return [clip for group in entries.values() for entry, clip in group
                    if entry.checkState() == Qt.Checked]

        def update_selection():
            count = len(selected_clips())
            import_button.setText(f'Importieren ({count})')
            import_button.setEnabled(count > 0)

        for listing in entries:
            listing.itemChanged.connect(update_selection)
        update_selection()
        buttons.accepted.connect(dialog.accept)
        buttons.rejected.connect(dialog.reject)
        layout.addWidget(buttons)
        timer.start(75)
        try:
            result = dialog.exec()
        finally:
            timer.stop()
            preview_worker.shutdown(wait=False, cancel_futures=True)
        if result != QDialog.Accepted:
            return
        selected = selected_clips()
        if not selected:
            return
        project = self.project

        def perform():
            errors, videos, photos = [], 0, 0
            for clip in selected:
                try:
                    if clip.category == 'PICTURE':
                        project.import_photo(clip.video)
                        photos += 1
                    else:
                        project.import_media(clip.video, camera_clip=clip)
                        videos += 1
                except Exception as error:
                    errors.append(f'{clip.video.name}: {error}')
            return errors, videos, photos

        def completed(result):
            errors, videos, photos = result
            self.populate()
            if errors:
                QMessageBox.warning(self, 'Kenwood-Import', '\n'.join(errors))
            if videos:
                self.media.setCurrentRow(len(project.data["media"]) - videos)
            if photos:
                QMessageBox.information(self, 'Fotoimport', f'{photos} Foto(s) in {project.root / "photos"}')

        self.job(perform, completed)

    def select(self, index):
        self.player.stop()
        self.player.setSource(QUrl())
        self.item = None
        self.strip.set_media()
        self.photo_view.clear()
        self.photo_view.hide()
        self.video.show()
        self.marks.setText('IN —   OUT —')
        self.telemetry_tracks = []
        self.telemetry.setText(NO_TELEMETRY.replace("km/h", self.instruments.unit))
        self.instruments.set_tracks()
        if index < 0 or not self.project:
            return
        videos = self.project.data['media']
        if index >= len(videos):
            path = self.photo_rows[index - len(videos)]
            reader = QImageReader(str(path))
            reader.setAutoTransform(True)
            if reader.size().isValid():
                reader.setScaledSize(reader.size().scaled(self.video.size(), Qt.KeepAspectRatio))
            pixmap = QPixmap.fromImage(reader.read())
            self.photo_view.setText('Foto kann nicht angezeigt werden' if pixmap.isNull() else '')
            if not pixmap.isNull():
                self.photo_view.setPixmap(pixmap)
            self.video.hide()
            self.photo_view.show()
            return
        self.item = videos[index]
        self.update_marks()
        if not self.project.path(self.item).is_file():
            self.statusBar().showMessage('Medium offline · Datei über Relink wieder verbinden')
            return
        project, item = self.project, self.item
        def ready(result):
            paths, data = result
            self.instruments.set_tracks(data, item["duration_ms"])
            if data:
                self.telemetry_tracks = [([row["ms"] for row in data[key]], data[key])
                                         for key in ("gps", "acceleration")]
                self.update_telemetry(0)
            self.player.setSource(QUrl.fromLocalFile(str(project.path(item))))
            self.strip.set_media(paths, item['duration_ms'])
        self.job(lambda: (project.thumbnails(item), project.load_telemetry(item)), ready)

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

    def reserve_time_width(self, duration):
        sample = timestamp(duration)
        metrics = self.time.fontMetrics()
        widest = max('0123456789', key=metrics.horizontalAdvance)
        sample = ''.join(widest if char.isdigit() else char for char in sample)
        self.time.setFixedWidth(metrics.horizontalAdvance(f'{sample} / {sample}') + 8)

    def update_duration(self, duration):
        self.seek.setMaximum(duration)
        self.reserve_time_width(duration)
        self.position(self.player.position())

    def position(self, value):
        if not self.seek.isSliderDown():
            self.seek.setValue(value)
        self.strip.set_position(value)
        self.instruments.position = value
        self.instruments.update()
        self.update_telemetry(value)
        self.time.setText(f'{timestamp(value)} / {timestamp(self.player.duration())}')

    def change_speed_unit(self, unit):
        self.settings.setValue('telemetry/unit', unit)
        self.instruments.unit = unit
        self.instruments.rebuild()
        if self.telemetry_tracks:
            self.update_telemetry(self.player.position())
        else:
            self.telemetry.setText(NO_TELEMETRY.replace('km/h', unit))

    def update_color_button(self, button, label, index):
        sample = QPixmap(14, 14)
        sample.fill(self.instruments.colors[index])
        button.setText(label)
        button.setIcon(QIcon(sample))
        button.setToolTip(f'Linienfarbe ändern: {label}')

    def choose_line_color(self, index, label, button):
        color = QColorDialog.getColor(self.instruments.colors[index], self, f'Linienfarbe: {label}')
        if color.isValid():
            self.settings.setValue(f'telemetry/color{index}', color.name())
            self.instruments.colors[index] = color
            self.update_color_button(button, label, index)
            self.instruments.update()

    def update_telemetry(self, value):
        if not self.telemetry_tracks:
            return
        samples = []
        for (times, rows), max_age in zip(self.telemetry_tracks, (500, 100)):
            index = bisect_right(times, value) - 1
            samples.append(rows[index] if index >= 0 and value - times[index] < max_age else {})
        gps, accel = samples
        speed = gps.get('speed_kmh')
        channels = accel.get('channels')
        self.instruments.speed = speed
        self.instruments.update()
        unit = self.instruments.unit
        first = (f'— {unit} · Keine GPS-Geschwindigkeit' if speed is None
                 else f'{display_speed(speed, unit):.1f} {unit} · GPS')
        second = 'Keine Daten' if channels is None else ' / '.join(f'{v:+.3f}' for v in channels) + ' (Rohwerte)'
        text = f'{first} · Zeitzuordnung geschätzt\nG-Sensor · {second}'
        if text != self.telemetry.text():
            self.telemetry.setText(text)

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
    window = Window()
    window.show()
    QTimer.singleShot(0, window.show_project_picker)
    sys.exit(app.exec())


if __name__ == '__main__':
    main()
