#!/usr/bin/env bash
set -euo pipefail
cd -- "$(dirname -- "${BASH_SOURCE[0]}")"
# Quote the executable for the Desktop Entry Exec field, including literal %.
python - <<'PY'
import os
from pathlib import Path

exe = str(Path('start.sh').resolve())
if any(c in exe for c in '\r\n'):
    raise SystemExit('Zeilenumbrüche im Projektpfad werden nicht unterstützt.')
escaped = ''.join(('\\' if c in '\\"$`' else '') + c for c in exe)
escaped = escaped.replace('\\', '\\\\').replace('%', '%%')
folder = Path(os.environ.get('XDG_DATA_HOME') or Path.home() / '.local/share') / 'applications'
folder.mkdir(parents=True, exist_ok=True)
path = folder / 'dashcam-studio.desktop'
path.write_text('[Desktop Entry]\nType=Application\nName=DashCam Studio\n'
                'Comment=Dashcam-Aufnahmen ansehen und schneiden\n'
                f'Exec=bash "{escaped}"\nIcon=video-x-generic\n'
                'Terminal=false\nCategories=AudioVideo;Video;\n', encoding='utf-8')
print(path)
PY
