# Changelog

All notable changes to **Pipecat MCP Server** will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.0.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

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
