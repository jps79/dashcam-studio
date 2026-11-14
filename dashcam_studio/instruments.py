"""Playback instruments; GPS and uncalibrated sensor channels use separate scales."""
import math
from PySide6.QtCore import Qt, QRectF, QPointF
from PySide6.QtGui import QColor, QPainter, QPainterPath, QPen, QPalette, QTransform
from PySide6.QtWidgets import QWidget

DEFAULT_COLORS = ('#1683c4', '#e34955', '#2c9b4d', '#a65ee2')


def display_speed(kmh, unit):
    return kmh / 1.609344 if unit == 'mph' else kmh


class Instruments(QWidget):
    def __init__(self):
        super().__init__()
        self.setFixedHeight(176)
        self.colors = [QColor(c) for c in DEFAULT_COLORS]
        self.unit = 'km/h'
        self.duration = self.position = 0
        self.speed = None
        self.data = {}
        self.paths = []
        self.speed_limit = 120
        self.sensor_limit = 1

    def set_tracks(self, data=None, duration=0):
        self.data = data or {}
        self.duration = duration
        self.position = 0
        self.speed = None
        self.rebuild()

    def rebuild(self):
        gps = [(r['ms'], display_speed(r['speed_kmh'], self.unit)
                if r.get('speed_kmh') is not None else None) for r in self.data.get('gps', [])]
        accel = self.data.get('acceleration', [])
        step = 20
        biggest = max((v for _, v in gps if v is not None), default=0)
        self.speed_limit = max(60, math.ceil(biggest / step) * step)
        self.sensor_limit = max(1, max((abs(v) for r in accel for v in r['channels']), default=0))
        self.paths = [self.make_path(gps, self.speed_limit, 0, 500)]
        for channel in range(3):
            self.paths.append(self.make_path([(r['ms'], r['channels'][channel]) for r in accel],
                                             self.sensor_limit * 2, .5, 100))
        self.update()

    def make_path(self, samples, scale, zero, interval):
        path = QPainterPath()
        previous = None
        for ms, value in samples:
            if value is None or not self.duration:
                previous = None
                continue
            x, y = ms / self.duration, 1 - zero - value / scale
            if previous is None or ms - previous > interval:
                path.moveTo(x, y)
                path.lineTo(x + .001, y)
            else:
                path.lineTo(x, y)
            previous = ms
        return path

    def paintEvent(self, event):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        palette = self.palette()
        text = palette.color(QPalette.Text)
        p.fillRect(self.rect(), palette.color(QPalette.Base))
        p.setPen(text)
        p.drawText(QRectF(0, 4, 112, 24), Qt.AlignCenter, 'GPS-Tacho')
        dial = QRectF(16, 33, 80, 80)
        p.setPen(QPen(palette.color(QPalette.Mid), 5))
        p.drawArc(dial, 225 * 16, -270 * 16)
        speed = None if self.speed is None else display_speed(self.speed, self.unit)
        if speed is not None:
            angle = math.radians(225 - 270 * min(1, speed / self.speed_limit))
            center = dial.center()
            p.setPen(QPen(self.colors[0], 3))
            p.drawLine(center, center + QPointF(34 * math.cos(angle), -34 * math.sin(angle)))
        p.setPen(text)
        p.drawText(QRectF(0, 115, 112, 26), Qt.AlignCenter,
                   f'{speed:.1f} {self.unit}' if speed is not None else f'— {self.unit}')
        p.drawText(QRectF(0, 141, 112, 23), Qt.AlignCenter,
                   'Keine GPS-Daten' if speed is None else f'0–{self.speed_limit} {self.unit}')
        if self.width() < 230:
            return
        width = self.width() - 130
        for title, top, indices, scale in (
            (f'GPS-Geschwindigkeit · {self.unit}', 0, (0,), f'0–{self.speed_limit}'),
            ('G-Sensor · Rohwerte', 87, (1, 2, 3), f'±{self.sensor_limit:.2f}'),
        ):
            rect = QRectF(120, top + 24, width, 58)
            p.setPen(text)
            p.drawText(120, top + 17, title + f'  ({scale})' if any(
                i < len(self.paths) and not self.paths[i].isEmpty() for i in indices) else title)
            p.setPen(palette.color(QPalette.Mid))
            p.drawRect(rect)
            p.save()
            p.setClipRect(rect.adjusted(0, -1, 0, 1))
            transform = QTransform().translate(rect.x(), rect.y()).scale(rect.width(), rect.height())
            available = False
            for i in indices:
                if i < len(self.paths) and not self.paths[i].isEmpty():
                    available = True
                    p.setPen(QPen(self.colors[i], 1.6))
                    p.drawPath(transform.map(self.paths[i]))
            if available and self.duration:
                x = rect.left() + rect.width() * min(1, self.position / self.duration)
                p.setPen(QPen(text, 1, Qt.DashLine))
                p.drawLine(QPointF(x, rect.top()), QPointF(x, rect.bottom()))
            elif not available:
                p.setPen(text)
                p.drawText(rect, Qt.AlignCenter, 'Keine Daten')
            p.restore()
