# Changelog

## Unreleased

- Added a simple Windows desktop interface.
- Added fast pause-guided Whisper chapter detection.
- Added expected-chapter validation and local reference fallbacks.
- Added chapter repair, insertion, editing, and deletion.
- Added a silent Windows launcher.
- Added progress, elapsed time, estimated time remaining, and live status messages.
- Added a long-book warning, Cancel button, and accidental-close protection.
- Added expected-count quality gating and increasingly sensitive automatic retries.
- Added a thorough full-book fallback scan and refusal to create known-incomplete results.
- Added Automatic, Require NVIDIA GPU, and CPU-only modes with a real CUDA execution test.
- Added a visible Report a Bug button and guided GitHub issue form.
- Added an AMD Vulkan mode using a user-selected whisper.cpp executable and GGML model, including a real backend test.
- Replaced manual AMD configuration with automatic GPU detection, verified one-time engine/model downloads, installation, and chunked Vulkan transcription.
- Tuned AMD Vulkan feeding based on available CPU cores and added live real-time transcription-speed reporting.
- Added support for audiobooks that announce chapters as isolated numbers instead of saying the word "Chapter."
- Added local context scoring, silence evidence, ordered sequence selection, confidence levels, and a detailed chapter-validation report.
- Added bold green live chapter discoveries and a continuously updated found-versus-expected chapter counter.
- Replaced automatic repeat scans with one pass per run and an optional, user-controlled retry settings dialog.
- Added a two-hour zero-chapter safety stop and recognition for word-only headings such as "Seven." or "Seven. The story continues...".
- Made ordered validation tolerate missing chapter numbers, added an expected-progress health check, and added verified print-page interpolation for recordings that announce pages instead of chapters.
- Replaced book-specific Python constants with an external reference catalogue, added MP3 metadata/folder identification, community-catalogue updates, Open Library and Google Books lookup, local opening transcription fallback, caching, edition confirmation, and fuzzy chapter-title matching.
- Preserved source audio and avoided software-version labels in generated filenames.
