# Entwicklungsübergabe — 27.10.2026

## Ziel

DashCam Studio für CachyOS/Arch Linux. PySide6/Qt, ffmpeg/ffprobe. Zuerst normale Testvideos, später DashCam-Telemetrie (Kenwood DRV-N520); echte Kenwood-Dateien liegen bisher nicht vor.

## Implementiert

- Dunkle Desktopoberfläche mit Qt-Multimedia-Player, Lautstärke und Standardnavigation.
- Nichtdestruktive Projektverwaltung mit standardmäßig kopierten, hashgeprüften Medien, optionalen externen Referenzen, Metadaten, Offline-Anzeige und Relinking identischer Dateien.
- Cache für zwölf Vorschaubilder und optionale Proxys. Versions-/Inhaltsbasierte Invalidierung.
- IN/OUT pro Medium und neu kodierter MP4-Export ohne Überschreiben vorhandener Dateien.
- Vollbild mit Monitorwahl. Geschwindigkeit/G-Sensor explizit ohne Daten.
- Zuletzt behoben: Filmstreifen hatte keine synchrone Positionsmarkierung und abweichende Geometrie gegenüber dem Slider. `timeline.py` verwendet eine gemeinsame Zeit-/Pixelabbildung, Zeitlabels, gelben Abspielkopf und Abschnittsmarkierung. Klicken/Ziehen sucht die entsprechende Zeit.

## Aufbau

- `dashcam_studio/core.py`: Projektmodell, Analyse, Import, Cache, Proxy und Export, ohne Qt.
- `dashcam_studio/app.py`: Oberfläche und serieller Hintergrundworker, GUI-Projektsperre.
- `dashcam_studio/timeline.py`: Filmstreifen, Positionsabbildung und Mausnavigation.
- `tests/`: vier FFmpeg-/Projektintegrationstests sowie drei Qt-/Timeline-Tests.

## Verifiziert

Sieben Tests zuletzt erfolgreich mit Python 3.14.8, PySide6 6.12.0 und lokalem FFmpeg. GUI-Tests laufen mit `QT_QPA_PLATFORM=offscreen`; Audio wird darin ersetzt, da die isolierte Testumgebung keinen Audiozugriff hat. Tests erzeugen temporäre Videodateien. Ein synthetischer 5-s-Clip und ein 30-s-Clip mit Zeitanzeige und Testton liegen unter `demo/`.

```sh
QT_QPA_PLATFORM=offscreen .venv/bin/python -m unittest discover -s tests -v
```

## Nächste sinnvolle Schritte

- Die korrigierte Filmstreifenanzeige interaktiv mit dem 30-s-Clip prüfen.
- Ton und Vollbild auf dem tatsächlichen Linux-/Mehrmonitorsystem prüfen.
- Abbrechen/Fortschritt für lange Medienjobs, robustere Absturz-Wiederherstellung und Projektbackups ergänzen.
- Echte DashCam-Beispiele beschaffen, bevor ein Telemetrieparser entwickelt wird.

## Datenregeln

Originale ausschließlich lesen, nie verschieben/überschreiben/löschen. Medienordner und Metadaten sind Projektbestandteile, Cache ist regenerierbar. Exporte immer in neue Dateien. Keine erfundenen Telemetriewerte. Eigene Aufnahmen nicht versehentlich ins Quellcode-Repository übernehmen.
