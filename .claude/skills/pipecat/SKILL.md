---
name: pipecat
description: Start a voice conversation using the Pipecat MCP server
---

Start a voice conversation with the user using the Pipecat MCP server's start(), listen(), speak(), and stop() tools.

## Instructions

1. Call `start()` to initialize and spawn the voice agent
2. Use `speak()` to greet the user and let them know you're listening
3. Enter a conversation loop:
   - Use `listen()` to hear what the user says
   - Respond naturally using `speak()`
   - **DEFAULT BEHAVIOR: Keep the conversation going.** If the user says "no", "nothing", "that's it", "I'm good", "not right now", or similar responses to your questions, continue listening. They're just saying they don't need help at this moment, NOT that they want to end the call.
   - **ONLY end the conversation** when the user uses explicit ending phrases: "goodbye", "bye", "end the conversation", "disconnect", or "hang up"
   - When in doubt, keep listening. It's better to stay connected than to disconnect prematurely.
4. When ending, say goodbye using `speak()`, then call `stop()` to gracefully shut down the voice agent

## Guidelines

- Keep responses very brief, aim for 1-2 short sentences maximum
- Voice takes time to speak, so shorter is always better
- Be direct and skip unnecessary preamble or filler words
- Before any file system change (creating, editing, or deleting files), show the proposed changes in the terminal, then ask for verbal confirmation before applying
- Always call `stop()` when the conversation ends to properly clean up resources
