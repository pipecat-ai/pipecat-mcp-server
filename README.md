# Pipecat MCP Server

Pipecat MCP Server gives your AI agents a voice using [Pipecat](https://github.com/pipecat-ai/pipecat). It should work with any [MCP](https://modelcontextprotocol.io/)-compatible client, exposing four simple tools:

- **start()** / **stop()**: Start and stop the voice agent
- **listen()**: Wait for you to speak and return the transcription
- **speak(text)**: Say something back to you

## 🧭 Getting started

### Prerequisites

- Python 3.10 or later
- [uv](https://docs.astral.sh/uv/getting-started/installation/) package manager
- API keys for third-party services (Speech-to-Text, Text-to-Speech, ...)

By default, the voice agent uses [Deepgram](https://deepgram.com) for speech-to-text and [Cartesia](https://cartesia.ai/) for text-to-speech.

### Installation

```bash
uv tool install pipecat-ai-mcp-server
```

This will install the `pipecat-mcp-server` tool.

If you want to use different services or modify the Pipecat pipeline somehow, you will need to clone the repository:

```bash
git clone https://github.com/pipecat-ai/pipecat-mcp-server.git
```

and install your local version with:

```bash
uv tool install -e /path/to/repo/pipecat-mcp-server
```

## Running the server

First, set your API keys as environment variables:

```bash
export DEEPGRAM_API_KEY=your-deepgram-key
export CARTESIA_API_KEY=your-cartesia-key
```

Then start the server:

```bash
pipecat-mcp-server
```

This will make the Pipecat MCP Server available at `http://localhost:9090/mcp`.

## Auto-approving permissions

For hands-free voice conversations, you will need to auto-approve tool permissions. Otherwise, your agent will prompt for confirmation, which interrupts the conversation flow.

> ⚠️ **Warning**: Enabling broad permissions is at your own risk.

## Installing the Pipecat skill (recommended)

The [Pipecat skill](.claude/skills/pipecat/SKILL.md) provides a better voice conversation experience. It asks for verbal confirmation before making changes to files, adding a layer of safety when using broad permissions.

> ⚠️ **Warning**: Without the skill, if permissions are auto-approved, your agent won't ask for verbal confirmation before modifying your files.

## 💻 MCP Client: Claude Code

### Adding the MCP server

Register the MCP server:

```bash
claude mcp add pipecat --transport http http://localhost:9090/mcp --scope user
```

Scope options:
- `local`: Stored in `~/.claude.json`, applies only to this project
- `user`: Stored in `~/.claude.json`, applies to all projects
- `project`: Stored in `.mcp.json` in the project directory

### Auto-approving permissions

Create `.claude/settings.local.json` in your project directory:

```json
{
  "permissions": {
    "allow": [
      "Bash",
      "Read",
      "Edit",
      "Write",
      "WebFetch",
      "mcp__pipecat__*"
    ]
  }
}
```

This grants permissions for Bash commands, file operations, web fetching, and all Pipecat MCP tools without prompting.

### Starting a voice conversation

Install the Pipecat skill into `.claude/skills/pipecat/SKILL.md`, then run `/pipecat`.

Alternatively, just type something like "Let's have a voice conversation." (no verbal confirmation for file changes).

## 💻 MCP Client: Cursor

### Adding the MCP server

Register the MCP server by editing `~/.cursor/mcp.json`:

```json
{
  "mcpServers": {
    "pipecat": {
      "url": "http://localhost:9090/mcp"
    }
  }
}
```

### Auto-approving permissions

Go to the `Auto-Run` agent settings and configure it to `Run Everything`.

### Starting a voice conversation

Install the Pipecat skill into `.claude/skills/pipecat/SKILL.md` (Cursor supports Claude skills location), then run `/pipecat`.

Alternatively, just type something like "Let's have a voice conversation." (no verbal confirmation for file changes).

## 💻 MCP Client: OpenAI Codex

### Adding the MCP server

Register the MCP server:

```bash
codex mcp add pipecat --url http://localhost:9090/mcp
```

### Auto-approving permissions

If you start `codex` inside a version controlled project, you will be asked if you allow Codex to work on the folder without approval. Say `Yes`, which adds the following to `~/.codex/config.toml`.

```toml
[projects."/path/to/your/project"]
trust_level = "trusted"
```

### Starting a voice conversation

Install the Pipecat skill into `.codex/skills/pipecat/SKILL.md`, then run `$pipecat`.

Alternatively, just type something like "Let's have a voice conversation." (no verbal confirmation for file changes).

## 🗣️ Connecting to the voice agent

Once the voice agent starts, you can connect using different methods depending on how the server is configured.

### Pipecat Playground (default)

When no arguments are specified to the `pipecat-mcp-server` command, the server uses Pipecat's local playground. Connect by opening **http://localhost:7860** in your browser.

You can also run an ngrok tunnel that you can connect to remotely:

```
ngrok http --url=your-proxy.ngrok.app 7860
```

### Daily Prebuilt

To use Daily's WebRTC infrastructure, first install the server with the Daily dependency:

```bash
uv tool install pipecat-ai-mcp-server[daily]
```

Then, set the `DAILY_API_KEY` environment variable to your Daily API key and `DAILY_SAMPLE_ROOM_URL` to your desired Daily room URL and pass the `-d` argument to `pipecat-mcp-server`.

```bash
export DAILY_API_KEY=your-daily-api-key
export DAILY_SAMPLE_ROOM_URL=your-daily-room

pipecat-mcp-server -d
```

Connect by opening your Daily room URL (e.g., **https://yourdomain.daily.co/room**) in your browser. Daily Prebuilt provides a ready-to-use video/audio interface.

### Phone call

To connect via phone call, pass `-t <provider> -x <your-proxy>` where `<provider>` is one of `twilio`, `telnyx`, `exotel`, or `plivo`, and `<your-proxy>` is your ngrok tunnel domain (e.g., `your-proxy.ngrok.app`).

First, start your ngrok tunnel:

```bash
ngrok http --url=your-proxy.ngrok.app 7860
```

Then, run the Pipecat MCP server with your ngrok URL and the required environment variables for your chosen telephony provider.

| Provider | Environment Variables                     |
|----------|-------------------------------------------|
| Twilio   | `TWILIO_ACCOUNT_SID`, `TWILIO_AUTH_TOKEN` |
| Telnyx   | `TELNYX_API_KEY`                          |
| Exotel   | `EXOTEL_API_KEY`, `EXOTEL_API_TOKEN`      |
| Plivo    | `PLIVO_AUTH_ID`, `PLIVO_AUTH_TOKEN`       |

#### Twilio

```bash
export TWILIO_ACCOUNT_SID=your-twilio-account-sid
export TWILIO_AUTH_TOKEN=your-twilio-auth-token

pipecat-mcp-server -t twilio -x your-proxy.ngrok.app
```

Configure your provider's phone number to point to your ngrok tunnel, then call your number to connect.

## 🧪 Experimental: Screen Capture

You can enable screen capture to stream your screen (or a specific window) to the Pipecat Playground or Daily room. This lets you see what's happening on your computer remotely while having a voice conversation with the agent.

### Environment Variables

| Variable                            | Description                                                        |
|-------------------------------------|--------------------------------------------------------------------|
| `PIPECAT_MCP_SERVER_SCREEN_CAPTURE` | Set to any value (e.g., `1`) to enable screen capture              |
| `PIPECAT_MCP_SERVER_SCREEN_WINDOW`  | Optional. Window name to capture (partial match, case-insensitive) |

### Example Usage

Capture your entire primary monitor:

```bash
export PIPECAT_MCP_SERVER_SCREEN_CAPTURE=1
pipecat-mcp-server
```

Capture a specific window by name:

```bash
export PIPECAT_MCP_SERVER_SCREEN_CAPTURE=1
export PIPECAT_MCP_SERVER_SCREEN_WINDOW="claude"
pipecat-mcp-server
```

### Important Notes

- Window capture is based on **window coordinates**, not window content. If another window overlaps the target window, the overlapping content will be captured.
- The capture region updates dynamically if the target window is moved.
- If the specified window is not found, capture falls back to the full screen.

## 📚 What's Next?

- **Customize services**: Edit `agent.py` to use different STT/TTS providers (ElevenLabs, OpenAI, etc.)
- **Change transport**: Configure for Twilio, WebRTC, or other transports
- **Add to your project**: Use this as a template for voice-enabled MCP tools
- **Learn more**: Check out [Pipecat's docs](https://docs.pipecat.ai/) for advanced features
- **Get help**: Join [Pipecat's Discord](https://discord.gg/pipecat) to connect with the community
