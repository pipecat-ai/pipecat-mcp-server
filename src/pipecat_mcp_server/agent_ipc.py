#
# Copyright (c) 2026, Daily
#
# SPDX-License-Identifier: BSD 2-Clause License
#

"""Inter-process communication for the Pipecat MCP server.

This module manages the IPC queues and child process lifecycle for communication
between the MCP server (parent) and the Pipecat voice agent (child). The child
process runs separately to avoid stdio collisions with the MCP protocol.
"""

import asyncio
import multiprocessing
import queue as queue_module
from typing import Optional

from loguru import logger

# Use spawn to avoid issues with forking from async context Fork copies the
# parent's state (event loop, file descriptors, locks) which can cause
# issues. Spawn creates a fresh Python interpreter.
multiprocessing.set_start_method("spawn", force=True)

_cmd_queue: Optional[multiprocessing.Queue] = None
_response_queue: Optional[multiprocessing.Queue] = None
_pipecat_process: Optional[multiprocessing.Process] = None


def _cleanup():
    """Clean up the pipecat child process."""
    global _pipecat_process, _cmd_queue, _response_queue

    logger.debug(f"Checking if Pipecat MCP Agent process is actually running...")
    if _pipecat_process:
        # Force terminate if still alive
        if _pipecat_process.is_alive():
            logger.debug(f"Terminating Pipecat MCP Agent process (PID {_pipecat_process.ident})")
            _pipecat_process.terminate()
            _pipecat_process.join(timeout=1.0)

        # Kill if terminate didn't work
        if _pipecat_process.is_alive():
            logger.debug(f"Killing Pipecat MCP Agent process (PID {_pipecat_process.ident})")
            _pipecat_process.kill()
            _pipecat_process.join(timeout=1.0)

        _pipecat_process = None


def start_pipecat_process():
    """Start the Pipecat child process.

    Creates IPC queues and spawns a new process to run the Pipecat voice agent.
    Cleans up any existing process before starting a new one.
    """
    global _cmd_queue, _response_queue, _pipecat_process

    # Clean up any existing process first
    _cleanup()

    # Create IPC queues using spawn context
    _cmd_queue = multiprocessing.Queue()
    _response_queue = multiprocessing.Queue()

    # Start pipecat as separate process
    logger.debug(f"Starting Pipecat MCP Agent process...")
    _pipecat_process = multiprocessing.Process(
        target=run_pipecat_process,
        args=(_cmd_queue, _response_queue),
    )
    _pipecat_process.start()
    logger.debug(f"Started Pipecat MCP Agent process (PID {_pipecat_process.ident})")


def stop_pipecat_process():
    """Stop the pipecat child process (explicit cleanup)."""
    logger.debug(f"Stopping Pipecat MCP Agent process...")
    _cleanup()
    logger.debug(f"Stopped Pipecat MCP Agent")


def run_pipecat_process(cmd_queue: multiprocessing.Queue, response_queue: multiprocessing.Queue):
    """Entry point for the Pipecat child process.

    Initializes logging and runs the Pipecat main loop. This function is called
    in a separate process to avoid stdio collisions with the MCP protocol.

    Args:
        cmd_queue: Queue for receiving commands from the MCP server.
        response_queue: Queue for sending responses back to the MCP server.

    """
    global _cmd_queue, _response_queue

    import os
    import sys

    from loguru import logger

    logger.remove()
    logger.add(sys.stderr, level="DEBUG")

    _cmd_queue = cmd_queue
    _response_queue = response_queue

    # Change to package directory so pipecat_main() can find bot.py
    package_dir = os.path.dirname(__file__)
    os.chdir(package_dir)

    # Import and run the pipecat main (which will call our bot() function)
    from pipecat.runner.run import main as pipecat_main

    logger.debug("Pipecat MCP Agent process started. Launching Pipecat runner!")

    pipecat_main()

    logger.debug("Pipecat runner is done...")


async def send_response(response: dict):
    """Send a response from the child process to the MCP server.

    Args:
        response: Response dictionary to send.

    Raises:
        RuntimeError: If the Pipecat process has not been started.

    """
    if _response_queue is None:
        raise RuntimeError("Pipecat process not started")
    loop = asyncio.get_event_loop()
    await loop.run_in_executor(None, _response_queue.put, response)


async def read_request() -> dict:
    """Read a request from the MCP server in the child process.

    Blocks until a command is available in the queue.

    Returns:
        Request dictionary containing the command and arguments.

    Raises:
        RuntimeError: If the Pipecat process has not been started.

    """
    if _cmd_queue is None:
        raise RuntimeError("Pipecat process not started")
    loop = asyncio.get_event_loop()
    request = await loop.run_in_executor(None, _cmd_queue.get)
    return request


def _get_with_timeout(queue: multiprocessing.Queue, timeout: float = 0.5):
    """Get from queue with timeout to allow cancellation.

    Args:
        queue: The queue to read from.
        timeout: Timeout in seconds.

    Returns:
        Item from the queue.

    Raises:
        TimeoutError: If the timeout expires before an item is available.

    """
    try:
        return queue.get(timeout=timeout)
    except queue_module.Empty:
        raise TimeoutError("Queue get timed out")


def _check_process_alive():
    """Check if the pipecat process is still alive."""
    if _pipecat_process and not _pipecat_process.is_alive():
        raise RuntimeError("Voice agent process has stopped")


async def _wait_for_command_response(timeout: float = 0.5) -> dict:
    """Wait for response from child process with health checks."""
    if _response_queue is None:
        raise RuntimeError("Pipecat process not started")

    loop = asyncio.get_event_loop()

    while True:
        try:
            return await loop.run_in_executor(None, _get_with_timeout, _response_queue, timeout)
        except TimeoutError:
            _check_process_alive()
            await asyncio.sleep(0)  # Yield to allow cancellation


async def send_command(cmd: str, **kwargs) -> dict:
    """Send a command to the Pipecat child process and wait for response.

    Args:
        cmd: Command name (e.g., "listen", "speak", "stop").
        **kwargs: Additional arguments for the command.

    Returns:
        Response dictionary from the child process.

    """
    if _cmd_queue is None or _response_queue is None:
        raise RuntimeError("Pipecat process not started")

    request = {"cmd": cmd, **kwargs}

    # Send request to child process
    loop = asyncio.get_event_loop()
    await loop.run_in_executor(None, _cmd_queue.put, request)

    # Wait for response with cancellation support
    try:
        response = await _wait_for_command_response()
    except asyncio.CancelledError:
        logger.info(f"Command '{cmd}' was cancelled")
        raise RuntimeError(f"Command '{cmd}' was cancelled")

    # Check for errors in response
    if "error" in response:
        raise RuntimeError(response["error"])

    return response
