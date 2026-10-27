"""Filmstrip with a single time-to-pixel mapping for painting and seeking."""
from PySide6.QtCore import Qt, Signal, QRectF
from PySide6.QtGui import QPainter, QColor, QPixmap, QPen
from PySide6.QtWidgets import QWidget


def timestamp(ms):
    seconds, millis = divmod(max(0, int(ms)), 1000)
    minutes, seconds = divmod(seconds, 60)
    return f'{minutes:02}:{seconds:02}.{millis:03}'


class Filmstrip(QWidget):
    seekRequested = Signal(int)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.frames = []
        self.duration = 0
        self.position = 0
        self.setMinimumHeight(115)
        self.setMouseTracking(True)

    def set_media(self, paths=(), duration=0):
        self.frames = [QPixmap(path) for path in paths]
        self.duration = duration
        self.position = 0
        self.update()

    def set_position(self, value):
        self.position = max(0, min(value, self.duration))
        self.update()

    def time_at(self, x):
        return round(max(0, min(x / max(1, self.width() - 1), 1)) * self.duration)

    def mousePressEvent(self, event):
        if event.button() == Qt.LeftButton and self.duration:
            self.seekRequested.emit(self.time_at(event.position().x()))

    def mouseMoveEvent(self, event):
        self.setToolTip(timestamp(self.time_at(event.position().x())))
        if event.buttons() & Qt.LeftButton and self.duration:
            self.seekRequested.emit(self.time_at(event.position().x()))

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.fillRect(self.rect(), QColor('#10161e'))
        if not self.frames or not self.duration:
            return
        width = self.width() / len(self.frames)
        active = min(len(self.frames) - 1, int(self.position / self.duration * len(self.frames)))
        for index, frame in enumerate(self.frames):
            rect = QRectF(index * width, 0, width, self.height() - 23)
            painter.drawPixmap(rect, frame, QRectF(frame.rect()))
            painter.setPen(QColor('#dde5ef'))
            painter.drawText(QRectF(index * width + 3, self.height() - 22, width - 6, 20),
                             Qt.AlignLeft | Qt.AlignVCenter, timestamp(index * self.duration / len(self.frames)))
            if index == active:
                painter.setPen(QPen(QColor('#46b8dc'), 2))
                painter.drawRect(rect.adjusted(1, 1, -1, -1))
        x = self.position / self.duration * (self.width() - 1)
        painter.setPen(QPen(QColor('#ffcc55'), 3))
        painter.drawLine(round(x), 0, round(x), self.height())
