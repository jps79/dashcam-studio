"""Qt-independent project model and media services. Sources are read-only inputs."""
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import tempfile
import uuid

SCHEMA = 1
CACHE_VERSION = 'v1-160x90-12-h264-720'


def atomic_json(path, value):
    path = Path(path)
    fd, tmp = tempfile.mkstemp(dir=path.parent, prefix='.save-')
    try:
        with os.fdopen(fd, 'w') as stream:
            json.dump(value, stream, indent=2, ensure_ascii=False)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(tmp, path)
    finally:
        Path(tmp).unlink(missing_ok=True)


def run(args):
    result = subprocess.run(args, capture_output=True, text=True)
    if result.returncode:
        raise RuntimeError(result.stderr[-3000:] or 'Medienprozess fehlgeschlagen')
    return result.stdout


def fingerprint(path):
    digest = hashlib.sha256()
    with Path(path).open('rb') as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b''):
            digest.update(block)
    return digest.hexdigest()


def probe(path):
    data = json.loads(run(['ffprobe', '-v', 'error', '-show_format', '-show_streams', '-of', 'json', str(path)]))
    if not any(s['codec_type'] == 'video' for s in data['streams']):
        raise ValueError('Datei enthält keine Videospur')
    data['duration_ms'] = round(float(data.get('format', {}).get('duration', 0)) * 1000)
    if data['duration_ms'] <= 0:
        raise ValueError('Keine gültige Videodauer gefunden')
    return data


class Project:
    def __init__(self, root, data):
        self.root = Path(root).resolve()
        self.data = data

    @classmethod
    def create(cls, root):
        root = Path(root).resolve()
        root.mkdir(parents=True, exist_ok=True)
        if any(root.iterdir()):
            raise ValueError('Bitte einen leeren Projektordner wählen')
        for name in ('media', 'metadata', 'cache', 'exports', 'telemetry'):
            (root / name).mkdir()
        project = cls(root, {'schema': SCHEMA, 'id': uuid.uuid4().hex, 'media': []})
        project.save()
        return project

    @classmethod
    def open(cls, root):
        root = Path(root).resolve()
        data = json.loads((root / 'project.json').read_text())
        if data.get('schema') != SCHEMA:
            raise ValueError('Nicht unterstützte Projektversion')
        project = cls(root, data)
        for item in data['media']:
            project.path(item)  # validate persisted paths before use
        return project

    def save(self):
        atomic_json(self.root / 'project.json', self.data)

    def path(self, item):
        if item['managed']:
            path = (self.root / item['path']).resolve()
            if not path.is_relative_to(self.root / 'media'):
                raise ValueError('Ungültiger verwalteter Medienpfad')
            return path
        return Path(item['path']).resolve()

    def import_media(self, source, managed=True, *, camera_clip=None):
        source = Path(source).resolve(strict=True)
        metadata = probe(source)
        identity = fingerprint(source)
        uid = uuid.uuid4().hex
        target = self.root / 'media' / (uid + source.suffix.lower())
        if managed:
            try:
                with source.open('rb') as src, target.open('xb') as dst:
                    shutil.copyfileobj(src, dst)
                if fingerprint(target) != identity or fingerprint(source) != identity:
                    raise ValueError('Quelle wurde während des Imports verändert')
            except Exception:
                target.unlink(missing_ok=True)
                raise
        item = {'id': uid, 'name': source.name, 'original': str(source),
                'path': str(target.relative_to(self.root)) if managed else str(source),
                'managed': managed, 'sha256': identity, 'duration_ms': metadata['duration_ms'],
                'in_ms': 0, 'out_ms': metadata['duration_ms'], 'telemetry': None}
        metadata_path = self.root / 'metadata' / (uid + '.json')
        raw_path = self.root / 'telemetry' / (uid + '.nmea')
        normalized = raw_path.with_suffix('.json')
        try:
            if camera_clip is not None:
                from .kenwood import ADAPTER, parse
                item.update(camera=ADAPTER, category=camera_clip.category)
                if camera_clip.sidecar is not None:
                    raw = camera_clip.sidecar.read_bytes()
                    raw_path.parent.mkdir(exist_ok=True)
                    raw_path.write_bytes(raw)
                    atomic_json(normalized, parse(raw, item['duration_ms']))
                    item['telemetry'] = {'adapter': ADAPTER, 'video_sha256': identity}
            atomic_json(metadata_path, metadata)
            self.data['media'].append(item)
            self.save()
        except Exception:
            if item in self.data['media']:
                self.data['media'].remove(item)
            for path in (metadata_path, raw_path, normalized, target):
                path.unlink(missing_ok=True)
            raise
        return item

    def photos(self):
        from .kenwood import PHOTO_SUFFIXES
        hidden = set(self.data.get('removed_photos', []))
        return sorted(path for path in (self.root / 'photos').glob('*')
                      if path.is_file() and path.suffix.lower() in PHOTO_SUFFIXES
                      and path.name not in hidden)

    def remove_entry(self, *, media=None, photo=None):
        """Remove a library entry without deleting any file."""
        if (media is None) == (photo is None):
            raise ValueError('Genau einen Eintrag auswählen')
        if photo is not None:
            if photo not in self.photos():
                raise ValueError('Foto gehört nicht zur Projektliste')
            previous = self.data.get('removed_photos', [])
            self.data['removed_photos'] = [*previous, photo.name]
            try:
                self.save()
            except Exception:
                self.data['removed_photos'] = previous
                raise
        else:
            items = self.data['media']
            index = items.index(media)
            items.pop(index)
            try:
                self.save()
            except Exception:
                items.insert(index, media)
                raise

    def import_photo(self, source):
        from .kenwood import PHOTO_SUFFIXES
        source = Path(source)
        if source.suffix.lower() not in PHOTO_SUFFIXES:
            raise ValueError('Nur JPEG-Fotos werden unterstützt')
        folder = self.root / 'photos'
        folder.mkdir(exist_ok=True)
        target = folder / source.name
        if target.exists() and fingerprint(target) == fingerprint(source):
            previous = self.data.get('removed_photos', [])
            if target.name in previous:
                self.data['removed_photos'] = [name for name in previous if name != target.name]
                try:
                    self.save()
                except Exception:
                    self.data['removed_photos'] = previous
                    raise
            return target
        if target.exists():
            target = folder / f'{source.stem}-{uuid.uuid4().hex}{source.suffix}'
        with tempfile.NamedTemporaryFile(dir=folder, delete=False) as tmp:
            staged = Path(tmp.name)
            try:
                with source.open('rb') as original:
                    shutil.copyfileobj(original, tmp)
                tmp.flush()
                os.link(staged, target)
            finally:
                staged.unlink(missing_ok=True)
        return target

    def load_telemetry(self, item):
        info = item.get('telemetry')
        if not isinstance(info, dict) or info.get('video_sha256') != item['sha256']:
            return None
        uid = item['id']
        if uuid.UUID(hex=uid).hex != uid:
            raise ValueError('Ungültige Medien-ID')
        path = self.root / 'telemetry' / (uid + '.json')
        if not path.is_file():
            return None
        return json.loads(path.read_text())

    def refresh(self, item):
        path = self.path(item)
        identity = fingerprint(path)
        if identity != item['sha256']:
            info = probe(path)
            atomic_json(self.root / 'metadata' / (item['id'] + '.json'), info)
            item.update(sha256=identity, duration_ms=info['duration_ms'], in_ms=0, out_ms=info['duration_ms'])
            self.save()
        return path

    def relink(self, item, source):
        source = Path(source).resolve(strict=True)
        if fingerprint(source) != item['sha256']:
            raise ValueError('Relinking erfordert die identische Datei (SHA-256)')
        probe(source)
        if item['managed']:
            target = self.path(item)
            if target.exists():
                raise ValueError('Verwaltete Datei ist bereits vorhanden')
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(source, target)
        else:
            item['path'] = str(source)
        self.save()

    def cache_dir(self, item):
        key = hashlib.sha256((item['sha256'] + CACHE_VERSION).encode()).hexdigest()
        path = self.root / 'cache' / key
        path.mkdir(parents=True, exist_ok=True)
        return path

    def thumbnails(self, item):
        source = self.refresh(item)
        directory = self.cache_dir(item)
        paths = []
        for i in range(12):
            path = directory / f'thumb-{i:02}.jpg'
            if not path.exists():
                tmp = path.with_suffix('.part.jpg')
                try:
                    run(['ffmpeg', '-v', 'error', '-nostdin', '-y', '-ss', str(i * item['duration_ms'] / 12000),
                         '-i', str(source), '-frames:v', '1', '-vf', 'scale=160:90:force_original_aspect_ratio=decrease,pad=160:90:(ow-iw)/2:(oh-ih)/2', str(tmp)])
                    tmp.replace(path)
                finally:
                    tmp.unlink(missing_ok=True)
            paths.append(str(path))
        return paths

    def proxy(self, item):
        source = self.refresh(item)
        path = self.cache_dir(item) / 'proxy.mp4'
        if not path.exists():
            tmp = path.with_suffix('.part.mp4')
            try:
                run(['ffmpeg', '-v', 'error', '-nostdin', '-y', '-i', str(source), '-map', '0:v:0', '-map', '0:a:0?',
                     '-vf', "scale='min(1280,iw)':-2", '-c:v', 'libx264', '-preset', 'veryfast', '-crf', '28', '-c:a', 'aac', str(tmp)])
                tmp.replace(path)
            finally:
                tmp.unlink(missing_ok=True)
        return str(path)

    def export(self, item, destination):
        source = self.refresh(item)
        start, end = item['in_ms'], item['out_ms']
        if not 0 <= start < end <= item['duration_ms']:
            raise ValueError('IN muss vor OUT innerhalb des Videos liegen')
        destination = Path(destination).resolve()
        protected = [self.path(m) for m in self.data['media']] + [Path(m['original']).resolve() for m in self.data['media']]
        if destination.exists() or destination in protected:
            raise ValueError('Exportziel existiert bereits oder ist eine Originaldatei')
        if destination.suffix.lower() != '.mp4':
            raise ValueError('Bitte MP4 als Exportformat verwenden')
        fd, tmp = tempfile.mkstemp(dir=destination.parent, suffix='.mp4')
        os.close(fd)
        try:
            run(['ffmpeg', '-v', 'error', '-nostdin', '-y', '-i', str(source), '-ss', str(start / 1000),
                 '-t', str((end-start) / 1000), '-map', '0:v:0', '-map', '0:a:0?', '-c:v', 'libx264',
                 '-preset', 'veryfast', '-crf', '18', '-c:a', 'aac', '-movflags', '+faststart', tmp])
            os.link(tmp, destination)  # atomic, refuses an existing target
        finally:
            Path(tmp).unlink(missing_ok=True)
        return str(destination)
