# DashCam Studio – Rust-Unterprojekt (experimentell, ungetestet)

**AI-assisted. Zielplattformen: Linux und Windows.** Eigenständiger CLI-Prototyp mit einem gemeinsamen Rust-Codebestand. Dieser Stand wurde noch nicht kompiliert oder ausgeführt; es gibt keine fertige Windows-EXE und keinen Installer. Die Python-Anwendung bleibt der bisherige Desktop-Stand.

Der Prototyp listet Kenwood-Aufnahmen und JPEGs nach Kategorie auf. Videos und NMEA-Dateien werden anhand von Kategorie und Dateinamen zugeordnet. Ein ausgewähltes Medium wird mitsamt passender NMEA-Datei in einen neuen Zielordner außerhalb des gewählten Kartenordners kopiert. Bestehende Ziele werden nicht überschrieben. Die Nummern beziehen sich auf die aktuelle Kartenliste; nach Änderungen an der Karte erneut scannen.

Mit installiertem Rust und Cargo, vom Repository-Stamm aus:

```sh
cargo build --manifest-path rust/Cargo.toml --release
cargo run --manifest-path rust/Cargo.toml -- scan "/Pfad/zur/Karte"
cargo run --manifest-path rust/Cargo.toml -- import "/Pfad/zur/Karte" 1 "/Pfad/zum/neuen-Ziel"
```

Unter Windows gelten dieselben Befehle, beispielsweise mit `E:\` als Kartenpfad und `C:\Videos\Dashcam-Import` als neuem Zielordner. Beim üblichen Windows-MSVC-Ziel sind zusätzlich die passenden C++-Buildwerkzeuge erforderlich.

Offen: native Testbuilds auf Linux und Windows, modulare Adapter-Schnittstelle, Projektdateien und Telemetrieauswertung, anschließend Desktopoberfläche, Video, Zoom, Karte und Export. Es besteht noch keine Kompatibilität mit Python-Projektdateien.
