---
name: pipecat
description: Start a voice conversation using the Pipecat MCP server
---

Start a voice conversation using the Pipecat MCP server's start(), listen(), speak(), and stop() tools.

## Flow

1. Print a nicely formatted message with bullet point in the terminal with the following information:
   - The voice session is starting
   - Once ready, they can connect via the transport of their choice (Pipecat Playground, Daily room, or phone call)
   - Models are downloaded on the first user connection, so the first connection may take a moment
   - If the connection is not established and the user cannot hear any audio, they should check the terminal for errors from the Pipecat MCP server
2. Call `start()` to initialize the voice agent
3. Greet the user with `speak()`, then loop: `listen()` → `speak()`
4. If the user wants to end the conversation, ask for verbal confirmation before stopping. When in doubt, keep listening.
5. Once confirmed, say goodbye with `speak()`, then call `stop()`

## Guidelines

- Keep responses to 1-2 short sentences. Brevity is critical for voice.
- Before any change (files, PRs, issues, etc.), show the proposed change in the terminal and ask for verbal confirmation.
- Always call `stop()` when the conversation ends.
