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

## Abgleich mit dem UI-Zielbild

Vorhanden sind Video und Zoom, GPS-Tacho und OSM-Karte, Wiedergabegeschwindigkeit, Filmstreifen mit wählbarer Vorschauhöhe und IN/OUT, getrennte Geschwindigkeit-/G-Sensor-Kurven, Kanalfilter, Projektmedien und Exporte, Standbild und MP4-Export. Neben dem Tacho stehen Aufnahmedatum, Dauer sowie GPS-Durchschnitt und Maximum für vorhandene Messwerte. Projektänderungen werden automatisch gespeichert.

Noch offen: Menüstruktur wie im Entwurf, Positionskoordinaten direkt auf dem Videobild, separates Register der aktuellen Kanalwerte mit bestätigter Achszuordnung und Einheit, Zeitachsen-Zoom unabhängig von der Vorschauhöhe, Lesezeichen, eigener Schnittbereichsregler mit zwei Griffen, alternative Exportprofile und Karten-Vollbild. Satellitenbilder wurden auf Wunsch entfernt.

## Entwicklungsstand vom 15.11.2026 (AI-assisted)

- **Exporte:** Eigener Reiter für MP4- und Bilddateien mit Vorschau, Zeitstempel und MP4-Dauer. Ein Klick öffnet den Export; per Kontextmenü kann er nach Bestätigung in den Papierkorb verschoben werden. MP4-Exporte zeigen beim Öffnen einen Filmstreifen und die Audio-Wellenform.
- **Schnitt und Ton:** Die Wellenform folgt dem Abspielkopf und erlaubt Positionssprünge. Beim Export von Projektmedien kann die Tonspur entfallen oder in mehreren markierten Bereichen stummgeschaltet werden. Der ausgewählte Stummbereich ist gelb-orange. Der MP4-Export zeigt Vorbereitung, FFmpeg-Kodierfortschritt und Speichern in der Statusleiste.
- **Oberfläche:** Eigenes Kamera-Icon für Fenster, Starter und Dock; Abspielgeschwindigkeit, Filmstreifengröße und G-Sensor-Kanalfilter. Unter dem Tacho stehen Kameradatum und Startzeit, Dauer, GPS-Strecke sowie Durchschnitts- und Höchstgeschwindigkeit. Anzeigen und Bedienelemente ohne verfügbare Telemetrie werden ausgeblendet. OSM bleibt die Standardkarte, die Offline-Spur bleibt verfügbar. Die separate Straßennamensanzeige samt Overpass-Abrufen und die nicht zuverlässig ladende Vektorkarte wurden nach dem Versuch entfernt.
- **Externe Videoausgabe:** Separates Fenster mit Monitor- und Audioauswahl. Lokales Vollbild verwendet den aktuellen Bildschirm. Für den bisherigen Spiegelversuch kann GNOME Network Displays geöffnet werden; auf dem getesteten BRAVIA führte dieser Weg nicht zuverlässig zur Medienwiedergabe, auch außerhalb von Flatpak.
- **Direkter Chromecast-Test:** Optionales PyChromecast-Modul verwendet Googles Default Media Receiver für kompatible MP4-Dateien. Das Cast-Fenster bietet Gerätesuche, Verbinden/Trennen, Clipwechsel, Wiedergabe, Pause und Zeitposition. Der Receiver zieht die Datei mit HTTP-Teilabrufen vom Rechner. Der lokale Medienserver liefert nur den aktuellen Clip an die IP des verbundenen Empfängers und wird beim Trennen beendet. Die App zeigt Ladezustand bzw. einen ausbleibenden Dateiabruf. **Der MP4-Abruf am Sony BRAVIA wurde vom Nutzer erfolgreich bestätigt**, nachdem UFW den eingehenden TCP-Port 8765 gezielt für den Fernseher freigab. Keine pauschale Firewall-Freigabe oder Weiterleitung aus dem Internet nötig. YouTube-Cast im Browser war unabhängig davon erfolgreich, weil der Fernseher das Video dort direkt von YouTube lädt.
- **Noch offen:** Live-Zoom am TV ([#1 Custom Web Receiver](https://github.com/jps79/dashcam-studio/issues/1), [#2 Google-TV-App](https://github.com/jps79/dashcam-studio/issues/2)), AirPlay sowie direktes Abspielen von Kenwood-MOV ohne vorherigen MP4-Export. Vollständige Funktionsabnahme von Cast-Steuerung und Ton am BRAVIA steht noch aus.
- **Rust:** Der CLI-Prototyp wurde lokal unter Linux gebaut und mit synthetischen Daten für Scan, Kopie und Schutz gegen Überschreiben getestet. Windows-Build und Desktopoberfläche bleiben offen.

Dieser Eintrag beschreibt den lokalen Entwicklungsstand; die zugehörigen Änderungen am Anwendungscode werden mit diesem Dokumentations-Commit nicht veröffentlicht.
