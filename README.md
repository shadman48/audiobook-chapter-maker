# Audiobook Chapter Maker

A simple Windows app that detects spoken chapter headings in audiobook MP3s and creates chaptered `.m4b` audiobook files.

## Features

- Clean desktop interface for nontechnical users
- Faster local Whisper scanning around likely chapter breaks
- Local speech recognition after the initial model download
- Optional expected-chapter lookup and manual validation
- Missing-chapter reporting
- Add, edit, rename, or remove chapter markers
- Scan one minute near an approximate timestamp to recover a missing chapter
- Repair an existing `.m4b` without re-encoding its audio
- Preserves the original MP3 and earlier audiobook files
- Silent Windows launcher with progress shown inside the app
- Real progress and activity indicators, elapsed time, and estimated time remaining
- Long-book warning, cancellation, and protection against accidental closing

## Windows quick start

1. Download or clone the repository.
2. Open the `launchers` folder.
3. Double-click **Start Audiobook Maker V3.vbs**.
4. Choose an audiobook MP3 and follow the prompts.

The first run checks for Python and FFmpeg and creates a private Python environment. Whisper components and the speech model require an internet connection the first time they are installed or downloaded.

## Requirements

- Windows 10 or 11
- Python 3.9 or newer; Python 3.11 or 3.12 is recommended
- FFmpeg and ffprobe
- Several GB of free disk space

## Privacy

Audio processing runs locally. The application does not upload audiobook audio. The optional book-information lookup sends only an inferred book title to Google Books.

## Current status

This is an early public version under active development. Verify generated chapter lists before relying on them.
