"""DRV-N520 SD-card adapter. Relative telemetry timing is estimated."""
from dataclasses import dataclass
import math
import re
import subprocess
from datetime import datetime
from pathlib import Path

ADAPTER = 'kenwood-drv-n520'
CATEGORIES = ('MANUAL', 'NORMAL', 'EVENT', 'PARKING', 'PICTURE')
PHOTO_SUFFIXES = {'.jpg', '.jpeg'}


@dataclass(frozen=True)
class Clip:
    video: Path
    category: str
    sidecar: Path | None


def recording_time(path):
    """Kenwood filename clock, with no inferred timezone."""
    stem = Path(path).stem
    if re.fullmatch(r'[0-9]{12}', stem):
        try:
            return datetime.strptime('20' + stem, '%Y%m%d%H%M%S')
        except ValueError:
            pass
    return None


def preview_image(path):
    """Decode a frame to memory without writing to the card."""
    for offset in (('',) if Path(path).suffix.lower() in PHOTO_SUFFIXES else ('1', '0')):
        try:
            result = subprocess.run(
                ['ffmpeg', '-v', 'error', '-nostdin', *(['-ss', offset] if offset else []), '-i', str(path),
                 '-map', '0:v:0', '-frames:v', '1',
                 '-vf', 'scale=128:72:force_original_aspect_ratio=decrease,pad=128:72:(ow-iw)/2:(oh-ih)/2',
                 '-f', 'image2pipe', '-c:v', 'png', 'pipe:1'],
                capture_output=True, timeout=5)
        except (OSError, subprocess.TimeoutExpired):
            return b''
        if result.returncode == 0 and result.stdout:
            return result.stdout
    return b''


def scan(root):
    root = Path(root)
    clips = []
    for category in CATEGORIES:
        folder = root / category
        if not folder.is_dir():
            continue
        logs = root / 'SYSTEM' / 'NMEA' / category
        by_name = {f.stem.casefold(): f for f in logs.iterdir()
                   if not f.name.startswith('.') and f.is_file() and f.suffix.casefold() == '.nmea'} if logs.is_dir() else {}
        suffixes = PHOTO_SUFFIXES if category == 'PICTURE' else {'.mov'}
        clips.extend(Clip(f, category, by_name.get(f.stem.casefold()))
                     for f in sorted(folder.iterdir())
                     if not f.name.startswith('.') and f.is_file() and f.suffix.casefold() in suffixes)
    return clips


def coordinate(raw, hemisphere, positive, negative, limit):
    value = float(raw)
    degrees, minutes = divmod(value, 100)
    if not 0 <= minutes < 60 or not 0 <= degrees + minutes / 60 <= limit:
        raise ValueError('Ungültige Koordinate')
    if hemisphere not in (positive, negative):
        raise ValueError('Unbekannte Himmelsrichtung')
    return (degrees + minutes / 60) * (1 if hemisphere == positive else -1)


def parse(raw, duration_ms):
    gps, accel = [], []
    block, slot = -1, 0
    for line in raw.decode('ascii', errors='replace').splitlines():
        body, _, checksum = line.partition('*')
        fields = body.split(',')
        if fields[0] == '$GPRMC':
            block += 1
            slot = 0
            t = block * 500
            if t >= duration_ms:
                continue
            sample = {'ms': t, 'fix': False}
            try:
                crc = 0
                for char in body[1:]:
                    crc ^= ord(char)
                if len(checksum) == 2 and crc == int(checksum, 16) and fields[2] == 'A':
                    lat = coordinate(fields[3], fields[4], 'N', 'S', 90)
                    lon = coordinate(fields[5], fields[6], 'E', 'W', 180)
                    speed = float(fields[7]) if fields[7] else None
                    if speed is not None and (not math.isfinite(speed) or speed < 0):
                        speed = None
                    sample.update(fix=True, utc_time=fields[1], utc_date=fields[9],
                                  latitude=lat, longitude=lon,
                                  speed_kmh=speed * 1.852 if speed is not None else None)
            except (ValueError, IndexError, OverflowError):
                pass
            gps.append(sample)
        elif fields[0] == '$GSENS' and block >= 0:
            t = block * 500 + slot * 100
            slot += 1
            try:
                values = [float(v) for v in fields[1:]]
                if t < duration_ms and slot <= 5 and len(values) == 3 and all(map(math.isfinite, values)):
                    accel.append({'ms': t, 'channels': values})
            except ValueError:
                pass
    return {'schema': 1, 'adapter': ADAPTER, 'timing': 'estimated-record-order',
            'sensor_units': None, 'gps': gps, 'acceleration': accel}
