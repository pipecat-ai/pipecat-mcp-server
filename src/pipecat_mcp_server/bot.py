#
# Copyright (c) 2026, Daily
#
# SPDX-License-Identifier: BSD 2-Clause License
#

"""Bot entry point for the Pipecat MCP server.

This module is discovered by the Pipecat runner and provides the bot()
function that processes voice commands from the MCP server.
"""

from loguru import logger
from pipecat.runner.types import RunnerArguments

from pipecat_mcp_server.agent import create_agent
from pipecat_mcp_server.agent_ipc import read_request, send_response


async def bot(runner_args: RunnerArguments):
    """Start the Pipecat agent.

    Creates the voice agent and runs a command loop that processes requests
    from the MCP server via IPC queues. This function runs in the child process
    spawned by `agent_ipc.start_pipecat_process()`.

    Supported commands:
        listen: Wait for user speech, respond with `{"text": "..."}`.
        speak: Speak the provided text, respond with `{"ok": True}`.
        stop: Stop the agent and exit the loop, respond with `{"ok": True}`.

    Args:
        runner_args: Configuration from the Pipecat runner specifying
            transport type and connection settings.

    """
    # Create and start the agent
    agent = await create_agent(runner_args)
    await agent.start()

    logger.info("Voice agent started, processing commands...")

    while True:
        # Get command (blocking call run in executor to not block the event loop)
        request = await read_request()
        cmd = request.get("cmd")

        logger.debug(f"Command '{cmd}' received, processing...")

        try:
            if cmd == "listen":
                text = await agent.listen()
                await send_response({"text": text})
                logger.debug(f"Command '{cmd}' finished, returning: {text}")
            elif cmd == "speak":
                await agent.speak(request["text"])
                await send_response({"ok": True})
                logger.debug(f"Command '{cmd}' finished")
            elif cmd == "list_windows":
                windows = await agent.list_windows()
                await send_response({"windows": windows})
                logger.debug(f"Command '{cmd}' finished")
            elif cmd == "screen_capture":
                matched_id = await agent.screen_capture(request.get("window_id"))
                await send_response({"ok": True, "window_id": matched_id})
                logger.debug(f"Command '{cmd}' finished")
            elif cmd == "capture_screenshot":
                path = await agent.capture_screenshot()
                await send_response({"path": path})
                logger.debug(f"Command '{cmd}' finished")
            elif cmd == "stop":
                await agent.stop()
                await send_response({"ok": True})
                logger.debug(f"Command '{cmd}' finished")
            else:
                await send_response({"error": f"Unknown command: {cmd}"})
        except Exception as e:
            logger.warning(f"Error processing command '{cmd}': {e}")
            await send_response({"text": str(e)})
            break
