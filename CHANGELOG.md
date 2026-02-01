# Changelog

All notable changes to **Pipecat MCP Server** will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.0.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [0.0.10] - 2026-02-01

### Added

- New `list_windows()` MCP tool to list all open windows with title, app name,
  and window ID.

- New `screen_capture(window_id)` MCP tool to start or switch screen capture to
  a specific window or full screen during a voice conversation.

### Changed

- Screen capture dependencies are now included by default (no longer an optional
  `[screen]` extra).

- Screen capture is no longer configured via environment variables
  (`PIPECAT_MCP_SERVER_SCREEN_CAPTURE`, `PIPECAT_MCP_SERVER_SCREEN_WINDOW`).
  Use the `list_windows()` and `screen_capture()` tools instead.

## [0.0.9] - 2026-01-31

### Changed

- Linux X11 screen capture backend using python-xlib.

- Native macOS screen capture using ScreenCaptureKit. Supports true window-level
  capture not affected by overlapping windows.

## [0.0.8] - 2026-01-31

### Changed

- Updated to Pipecat >= 0.0.101.

## [0.0.7] - 2026-01-31

### Changed

- `KokoroTTSService` now uses `kokoro-onnx`.

## [0.0.6] - 2026-01-29

### Added

- Added `KokoroTTSService` processor.

- Added noise cancellation with `RNNoiseFilter`.

- Simplified the `/pipecat` skill instructions.

### Changed

- Replaced third-party STT/TTS services (Deepgram, Cartesia) with local models:
  Faster Whisper for speech-to-text and Kokoro for text-to-speech. No API keys
  required.

## [0.0.5] - 2026-01-28

### Fixed

- Fixed an issue that would cause an MCP session to crash and would force the
  MCP client to reconnect each time.

## [0.0.4] - 2026-01-26

### Fixed

- Fixed an issue where Daily clients couldn't reconnect after disconnecting.

## [0.0.3] - 2026-01-26

### Fixed

- Fixed premature exit of the `/pipecat` skill when user responds with phrases
  like "no", "nothing", or "that's it" instead of explicit ending phrases.

- Fixed an issue where WebRTC clients couldn't reconnect after disconnecting.
  The agent now properly handles disconnect/reconnect cycles.

- Fixed an issue where `pipecat-mcp-server` could hang indefinitely after
  pressing Ctrl-C.

## [0.0.2] - 2026-01-26

### Fixed

- Fixed an issue that would cause the Pipecat agent to not load if the optional
  `daily` dependency was not installed.

- Added missing support for `telnyx`, `plivo` and `exotel` telephony providers.

## [0.0.1] - 2026-01-26

Initial public release.
