"""Integration tests for the webhook listener server."""

from __future__ import annotations

import hashlib
import hmac
import json
from typing import TYPE_CHECKING

import pytest
from aiohttp import ClientSession

from phantom.conductor.queue import JobQueue
from phantom.conductor.triggers import WebhookListener

if TYPE_CHECKING:
    from pathlib import Path


def _sign(payload: bytes, secret: str) -> str:
    sig = hmac.new(secret.encode(), payload, hashlib.sha256).hexdigest()
    return f"sha256={sig}"


@pytest.mark.integration
class TestWebhookServer:
    async def test_signed_release_creates_job(self, tmp_path: Path) -> None:
        """Send a signed release.published payload, verify job is created."""
        secret = "test-secret-123"
        queue = JobQueue(lock_dir=tmp_path / "locks", max_depth=5)

        listener = WebhookListener(
            queue=queue,
            webhook_secret=secret,
            port=0,  # Let OS assign a port
            manifest_map={"my-repo": str(tmp_path / ".phantom.yml")},
        )

        # We need to start the server to get the actual port
        from aiohttp import web

        app = web.Application()
        app.router.add_post("/webhook/github", listener._handle_webhook)
        app.router.add_get("/health", listener._handle_health)

        runner = web.AppRunner(app)
        await runner.setup()
        site = web.TCPSite(runner, "127.0.0.1", 0)
        await site.start()

        # Get the actual port
        port = site._server.sockets[0].getsockname()[1]

        try:
            payload = json.dumps(
                {
                    "action": "published",
                    "release": {"tag_name": "v1.0.0"},
                    "repository": {"full_name": "org/my-repo", "name": "my-repo"},
                }
            ).encode()

            sig = _sign(payload, secret)

            async with (
                ClientSession() as session,
                session.post(
                    f"http://127.0.0.1:{port}/webhook/github",
                    data=payload,
                    headers={
                        "X-Hub-Signature-256": sig,
                        "X-GitHub-Event": "release",
                        "X-GitHub-Delivery": "test-delivery-1",
                        "Content-Type": "application/json",
                    },
                ) as resp,
            ):
                assert resp.status == 200
                data = await resp.json()
                assert data["status"] == "accepted"
                assert "job_id" in data

            # Verify job was queued
            assert queue.size == 1

        finally:
            await runner.cleanup()

    async def test_invalid_signature_rejected(self, tmp_path: Path) -> None:
        """Requests with invalid signatures should be rejected with 403."""
        secret = "test-secret-123"
        queue = JobQueue(lock_dir=tmp_path / "locks", max_depth=5)

        listener = WebhookListener(
            queue=queue,
            webhook_secret=secret,
            port=0,
            manifest_map={"my-repo": str(tmp_path / ".phantom.yml")},
        )

        from aiohttp import web

        app = web.Application()
        app.router.add_post("/webhook/github", listener._handle_webhook)

        runner = web.AppRunner(app)
        await runner.setup()
        site = web.TCPSite(runner, "127.0.0.1", 0)
        await site.start()
        port = site._server.sockets[0].getsockname()[1]

        try:
            payload = b'{"action": "published"}'
            async with (
                ClientSession() as session,
                session.post(
                    f"http://127.0.0.1:{port}/webhook/github",
                    data=payload,
                    headers={
                        "X-Hub-Signature-256": "sha256=bad_signature",
                        "X-GitHub-Event": "release",
                    },
                ) as resp,
            ):
                assert resp.status == 403

            assert queue.size == 0
        finally:
            await runner.cleanup()

    async def test_health_endpoint(self, tmp_path: Path) -> None:
        """Health check should return 200 with queue status."""
        queue = JobQueue(lock_dir=tmp_path / "locks", max_depth=5)
        listener = WebhookListener(
            queue=queue,
            webhook_secret="secret",
            port=0,
            manifest_map={},
        )

        from aiohttp import web

        app = web.Application()
        app.router.add_get("/health", listener._handle_health)

        runner = web.AppRunner(app)
        await runner.setup()
        site = web.TCPSite(runner, "127.0.0.1", 0)
        await site.start()
        port = site._server.sockets[0].getsockname()[1]

        try:
            async with (
                ClientSession() as session,
                session.get(f"http://127.0.0.1:{port}/health") as resp,
            ):
                assert resp.status == 200
                data = await resp.json()
                assert data["status"] == "ok"
                assert data["queue_size"] == 0
        finally:
            await runner.cleanup()

    async def test_ignored_event_returns_ignored(self, tmp_path: Path) -> None:
        """Events we don't handle should return 200 with status=ignored."""
        secret = "test-secret"
        queue = JobQueue(lock_dir=tmp_path / "locks", max_depth=5)

        listener = WebhookListener(
            queue=queue,
            webhook_secret=secret,
            port=0,
            manifest_map={},
        )

        from aiohttp import web

        app = web.Application()
        app.router.add_post("/webhook/github", listener._handle_webhook)

        runner = web.AppRunner(app)
        await runner.setup()
        site = web.TCPSite(runner, "127.0.0.1", 0)
        await site.start()
        port = site._server.sockets[0].getsockname()[1]

        try:
            payload = json.dumps({"zen": "Testing"}).encode()
            sig = _sign(payload, secret)

            async with (
                ClientSession() as session,
                session.post(
                    f"http://127.0.0.1:{port}/webhook/github",
                    data=payload,
                    headers={
                        "X-Hub-Signature-256": sig,
                        "X-GitHub-Event": "ping",
                    },
                ) as resp,
            ):
                assert resp.status == 200
                data = await resp.json()
                assert data["status"] == "ignored"

            assert queue.size == 0
        finally:
            await runner.cleanup()
