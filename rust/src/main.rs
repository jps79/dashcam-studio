//! Experimental cross-platform Kenwood import tool.
use std::{env, ffi::OsStr, fs, io, path::{Path, PathBuf}, process::ExitCode};

const CATEGORIES: [&str; 5] = ["MANUAL", "NORMAL", "EVENT", "PARKING", "PICTURE"];

struct Clip {
    category: &'static str,
    media: PathBuf,
    telemetry: Option<PathBuf>,
}

fn files(folder: &Path) -> io::Result<Vec<PathBuf>> {
    let entries = match fs::read_dir(folder) {
        Ok(entries) => entries,
        Err(error) if error.kind() == io::ErrorKind::NotFound => return Ok(Vec::new()),
        Err(error) => return Err(error),
    };
    let mut paths = Vec::new();
    for entry in entries {
        let entry = entry?;
        if entry.file_type()?.is_file() && !entry.file_name().to_string_lossy().starts_with('.') {
            paths.push(entry.path());
        }
    }
    paths.sort();
    Ok(paths)
}

fn extension(path: &Path, value: &str) -> bool {
    path.extension().and_then(OsStr::to_str).is_some_and(|ext| ext.eq_ignore_ascii_case(value))
}

fn scan(root: &Path) -> io::Result<Vec<Clip>> {
    if !root.is_dir() {
        return Err(io::Error::new(io::ErrorKind::NotFound, "Kartenordner nicht gefunden"));
    }
    let mut clips = Vec::new();
    for category in CATEGORIES {
        let logs = files(&root.join("SYSTEM").join("NMEA").join(category))?;
        for media in files(&root.join(category))? {
            let telemetry = if category == "PICTURE" {
                if !extension(&media, "jpg") && !extension(&media, "jpeg") { continue; }
                None
            } else {
                if !extension(&media, "mov") { continue; }
                logs.iter().find(|log| {
                    extension(log, "nmea") && log.file_stem().zip(media.file_stem())
                        .is_some_and(|(a, b)| a.to_string_lossy().eq_ignore_ascii_case(&b.to_string_lossy()))
                }).cloned()
            };
            clips.push(Clip { category, media, telemetry });
        }
    }
    Ok(clips)
}

fn copy_new(source: &Path, target: &Path) -> io::Result<()> {
    let mut input = fs::File::open(source)?;
    let mut output = fs::OpenOptions::new().write(true).create_new(true).open(target)?;
    let result = io::copy(&mut input, &mut output).and_then(|_| output.sync_all());
    drop(output);
    if result.is_err() { let _ = fs::remove_file(target); }
    result
}

fn import(root: &Path, target: &Path, clip: &Clip) -> io::Result<()> {
    let parent = target.parent().filter(|p| !p.as_os_str().is_empty()).unwrap_or(Path::new("."));
    if parent.canonicalize()?.starts_with(root.canonicalize()?) {
        return Err(io::Error::new(io::ErrorKind::InvalidInput, "Ziel muss außerhalb der SD-Karte liegen"));
    }
    fs::create_dir(target)?;
    let result = (|| {
        copy_new(&clip.media, &target.join(clip.media.file_name().unwrap()))?;
        if let Some(log) = &clip.telemetry {
            copy_new(log, &target.join(log.file_name().unwrap()))?;
        }
        Ok(())
    })();
    if result.is_err() { let _ = fs::remove_dir_all(target); }
    result
}

fn run() -> Result<(), Box<dyn std::error::Error>> {
    let args: Vec<_> = env::args_os().skip(1).collect();
    match args.as_slice() {
        [command, root] if command == "scan" => {
            for (index, clip) in scan(Path::new(root))?.iter().enumerate() {
                println!("{}\t{}\t{}\t{}", index + 1, clip.category, clip.media.display(),
                         if clip.telemetry.is_some() { "NMEA" } else { "—" });
            }
        }
        [command, root, number, target] if command == "import" => {
            let index = number.to_str().ok_or("Ungültige Nummer")?.parse::<usize>()?;
            let root = Path::new(root);
            let clips = scan(root)?;
            let clip = index.checked_sub(1).and_then(|i| clips.get(i)).ok_or("Eintrag nicht gefunden")?;
            import(root, Path::new(target), clip)?;
        }
        _ => return Err("Aufruf: dashcam-studio-rust scan <Karte> | import <Karte> <Nummer> <neuer Zielordner>".into()),
    }
    Ok(())
}

fn main() -> ExitCode {
    match run() {
        Ok(()) => ExitCode::SUCCESS,
        Err(error) => { eprintln!("{error}"); ExitCode::FAILURE }
    }
}
