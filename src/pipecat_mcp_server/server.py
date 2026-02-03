#
# Copyright (c) 2026, Daily
#
# SPDX-License-Identifier: BSD 2-Clause License
#

"""Pipecat MCP Server for voice I/O.

This server exposes voice tools via the MCP protocol, enabling any MCP client
to have voice conversations with users through a Pipecat pipeline.

Tools:
    start: Initialize and start the voice agent.
    listen: Wait for user speech and return transcribed text.
    speak: Speak text to the user via text-to-speech.
    stop: Gracefully shut down the voice pipeline.
"""

import sys

from loguru import logger
from mcp.server.fastmcp import FastMCP

from pipecat_mcp_server.agent_ipc import send_command, start_pipecat_process, stop_pipecat_process

logger.remove()
logger.add(sys.stderr, level="DEBUG")

# Create MCP server
mcp = FastMCP(name="pipecat-mcp-server", host="localhost", port=9090)


@mcp.tool()
async def start() -> bool:
    """Start a new Pipecat Voice Agent.

    Once the voice agent has started you can continuously use the listen() and
    speak() tools to talk to the user.

    Returns true if the agent was started successfully, false otherwise.
    """
    start_pipecat_process()
    return True


@mcp.tool()
async def listen() -> str:
    """Listen for user speech and return the transcribed text."""
    result = await send_command("listen")
    return result["text"]


@mcp.tool()
async def speak(text: str) -> bool:
    """Speak the given text to the user using text-to-speech.

    Returns true if the agent spoke the text, false otherwise.
    """
    await send_command("speak", text=text)
    return True


@mcp.tool()
async def list_windows() -> list[dict]:
    """List all open windows visible to the screen capture backend.

    Returns a list of objects with title, app_name, and window_id fields.

    Note: Multiple windows may appear for the same app (e.g., tabs, child
    frames). When in doubt about which window the user wants, ask for
    clarification before capturing.
    """
    result = await send_command("list_windows")
    return result.get("windows", [])


@mcp.tool()
async def screen_capture(window_id: int | None = None) -> int | None:
    """Start or switch screen capture to a window or full screen.

    Captures are streamed through the Pipecat pipeline. Use list_windows()
    to find available window IDs.

    Args:
        window_id: Window ID to capture (from list_windows()). If not provided,
            captures the full screen.

    Returns the window ID if the window was found, or None if it was not found
    or capturing full screen.

    """
    result = await send_command("screen_capture", window_id=window_id)
    return result.get("window_id")


@mcp.tool()
async def capture_screenshot() -> str:
    """Take a look at what's on screen.

    Use this when the user asks what you can see. Screen capture must
    already be started via screen_capture().

    Returns the absolute path to the saved image file.
    """
    result = await send_command("capture_screenshot")
    return result.get("path", "No screen capture available.")


@mcp.tool()
async def stop() -> bool:
    """Stop the voice pipeline and clean up resources.

    Call this when the voice conversation is complete to gracefully
    shut down the voice agent.

    Returns true if the agent was stopped successfully, false otherwise.
    """
    await send_command("stop")
    return True


def main():
    """Start the Pipecat MCP server.

    Runs the MCP server using stdio for communication with the MCP client.
    When the server exits, any running Pipecat agent process is cleaned up.
    """
    try:
        mcp.run(transport="streamable-http")
    except KeyboardInterrupt:
        logger.info("Ctrl-C detected, exiting!")
    finally:
        stop_pipecat_process()


if __name__ == "__main__":
    main()
