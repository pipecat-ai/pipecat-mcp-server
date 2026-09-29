#
# Copyright (c) 2026, Daily
#
# SPDX-License-Identifier: BSD 2-Clause License
#

"""Tests for the request and response pairing in the IPC layer."""

import asyncio
import queue

import pytest

from pipecat_mcp_server import agent_ipc


@pytest.fixture
def queues(monkeypatch):
    """Replace the IPC queues with in-process queues."""
    cmd_queue = queue.Queue()
    response_queue = queue.Queue()
    monkeypatch.setattr(agent_ipc, "_cmd_queue", cmd_queue)
    monkeypatch.setattr(agent_ipc, "_response_queue", response_queue)
    monkeypatch.setattr(agent_ipc, "_pipecat_process", None)
    monkeypatch.setattr(agent_ipc, "_active_request_id", None, raising=False)
    return cmd_queue, response_queue


async def _child_answer(reply: dict):
    """Play the child process: read one request and answer it."""
    request = await agent_ipc.read_request()
    await agent_ipc.send_response(reply)
    return request


@pytest.mark.asyncio
async def test_cancelled_listen_does_not_answer_the_next_command(queues):
    """A cancelled command leaves no stale response for the next one."""
    """A cancelled command leaves no stale response for the next one."""
    listen = asyncio.create_task(agent_ipc.send_command("listen"))
    await asyncio.sleep(0.1)
    listen.cancel()
    with pytest.raises(asyncio.CancelledError):
        await listen

    # The child was still listening, so it answers the cancelled command late,
    # after the reader thread of the cancelled call has timed out.
    await asyncio.sleep(1.0)
    stale = asyncio.create_task(_child_answer({"text": "stale words"}))
    await stale

    speak = asyncio.create_task(agent_ipc.send_command("speak", text="hello"))
    await _child_answer({"ok": True})
    response = await asyncio.wait_for(speak, timeout=5)

    assert response.get("ok") is True
    assert "text" not in response


@pytest.mark.asyncio
async def test_response_matches_its_request(queues):
    """A response that answers the current command is returned."""
    command = asyncio.create_task(agent_ipc.send_command("list_windows"))
    await _child_answer({"windows": []})
    response = await asyncio.wait_for(command, timeout=5)

    assert response["windows"] == []
