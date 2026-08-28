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
- Preserved source audio and avoided software-version labels in generated filenames.
