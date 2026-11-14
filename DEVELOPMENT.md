# Entwicklungsübergabe — 27.10.2026

## Ziel

DashCam Studio für CachyOS/Arch Linux. PySide6/Qt, ffmpeg/ffprobe. Zuerst normale Testvideos, später DashCam-Telemetrie (Kenwood DRV-N520); erste echte Kenwood-Aufnahmen wurden lokal analysiert.

## Architekturziel: weitere Kameras modular ergänzen

Weitere Hersteller und Modelle über separate, austauschbare Kameraadapter ergänzen. Gemeinsame Schnittstellen für Dateierkennung, Aufnahmezuordnung und normalisierte Telemetrie vorsehen; Player, Projektmodell und UI von modellspezifischen Parsern trennen. Unbekannte Modelle und fehlende Telemetrie dürfen die normale Videowiedergabe nicht verhindern. Jeden Adapter mit geeigneten Beispieldateien prüfen. Der erste Kenwood-Adapter ist umgesetzt; ein allgemeines Adapterregister ist geplant.

## Implementiert

- Dunkle Desktopoberfläche mit Qt-Multimedia-Player, Lautstärke und Standardnavigation.
- Nichtdestruktive Projektverwaltung mit standardmäßig kopierten, hashgeprüften Medien, optionalen externen Referenzen, Metadaten, Offline-Anzeige und Relinking identischer Dateien.
- Cache für zwölf Vorschaubilder und optionale Proxys. Versions-/Inhaltsbasierte Invalidierung.
- IN/OUT pro Medium und neu kodierter MP4-Export ohne Überschreiben vorhandener Dateien.
- Vollbild mit Monitorwahl. GPS-Geschwindigkeit und G-Sensor-Rohwerte bei Kenwood-Clips mit passenden Messdaten.
- Zuletzt behoben: Filmstreifen hatte keine synchrone Positionsmarkierung und abweichende Geometrie gegenüber dem Slider. `timeline.py` verwendet eine gemeinsame Zeit-/Pixelabbildung, Zeitlabels, gelben Abspielkopf und Abschnittsmarkierung. Klicken/Ziehen sucht die entsprechende Zeit.

## Aufbau

- `dashcam_studio/core.py`: Projektmodell, Analyse, Import, Cache, Proxy und Export, ohne Qt.
- `dashcam_studio/app.py`: Oberfläche und serieller Hintergrundworker, GUI-Projektsperre.
- `dashcam_studio/timeline.py`: Filmstreifen, Positionsabbildung und Mausnavigation.
- `tests/`: Integrationstests für Projektverwaltung, Kenwood-Import und Qt-Oberfläche.

## Verifiziert

24 Tests zuletzt erfolgreich mit Python 3.14.8, PySide6 6.12.0 und lokalem FFmpeg. GUI-Tests laufen mit `QT_QPA_PLATFORM=offscreen`; Audio wird darin ersetzt, da die isolierte Testumgebung keinen Audiozugriff hat. Tests erzeugen temporäre Videodateien. Ein synthetischer 5-s-Clip und ein 30-s-Clip mit Zeitanzeige und Testton liegen unter `demo/`.

```sh
QT_QPA_PLATFORM=offscreen .venv/bin/python -m unittest discover -s tests -v
```

## Nächste sinnvolle Schritte

- Die korrigierte Filmstreifenanzeige interaktiv mit dem 30-s-Clip prüfen.
- Ton und Vollbild auf dem tatsächlichen Linux-/Mehrmonitorsystem prüfen.
- Abbrechen/Fortschritt für lange Medienjobs, robustere Absturz-Wiederherstellung und Projektbackups ergänzen.
- Zeitversatz, Sensoreinheiten und Achszuordnung mit echten Aufnahmen verifizieren.

## Datenregeln

Originale ausschließlich lesen, nie verschieben/überschreiben/löschen. Medienordner und Metadaten sind Projektbestandteile, Cache ist regenerierbar. Exporte immer in neue Dateien. Keine erfundenen Telemetriewerte. Eigene Aufnahmen nicht versehentlich ins Quellcode-Repository übernehmen.

## Erster Kenwood-Import

`kenwood.py` erkennt die SD-Aufnahmekategorien, ordnet MOV und NMEA zu und normalisiert RMC/GSENS. Die Projektverwaltung sichert Video, Rohdatei und Telemetrie; Tests verwenden synthetische Testdaten. Zeitzuordnung bleibt geschätzt. GPS-Tacho und getrennte Linienplots mit konfigurierbaren Farben sind umgesetzt. Die Kartenansicht zeigt OSM oder die lokale GPS-Spur.

## Änderungen seit dem letzten veröffentlichten Codestand (14.11.2026)

- Oberfläche am Zielbild ausgerichtet: Video, GPS-Tacho und Karte oben; Filmstreifen und Messkurven darunter, Projektmedien rechts. Medienvorschauen zeigen Aufnahmedatum und Start–Ende nach Kamerauhr.
- Tacho bis 200 km/h, bei höheren GPS-Spitzen in 50-km/h-Schritten erweitert. Roter Bereich oberhalb von 130 km/h; Marken werden für mph umgerechnet.
- OpenStreetMap ist die Standardkarte, Offline-GPS-Spur bleibt verfügbar. Satelliten- und regionale Luftbilder wurden nach Erprobung entfernt. Der weiche Nachlauf ist auf 10–50 % Randabstand einstellbar (Vorgabe: 50 %).
- Erstes Videobild erscheint beim Auswählen vor dem Laden des Filmstreifens. Beim Suchen bleibt das letzte gültige Bild sichtbar. Softwaredekodierung ist wegen beobachteter Abstürze bei der Qt-Bildkonvertierung voreingestellt.
- Bildzoom per Mausrad und Verschieben per Maus. PNG-Einzelbilder und MP4-Schnitte verwenden den sichtbaren Ausschnitt aus der Originaldatei. IN/OUT-Griffe sind ziehbar; der Bereich kann einmal oder als Schleife abgespielt werden. Die Exportaktionen befinden sich unter dem Video, mit kurzen Hover-Hinweisen.
- Vollbild: Pfeile wechseln die Laufrichtung während der Wiedergabe (rückwärts ohne Ton). Pausiert springen sie ein Bild; Halten wiederholt Fünfer-Schritte. Enter öffnet den PNG-Speicherdialog.

Diese Übersicht dokumentiert den lokalen Entwicklungsstand; sie enthält keine Aufnahme- oder Fahrdaten.
