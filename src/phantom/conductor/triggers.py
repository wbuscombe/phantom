"""GitHub webhook listener and trigger handling.

Provides an async HTTP server that listens for GitHub webhook events
and creates jobs in the conductor's queue.
"""

from __future__ import annotations

import hashlib
import hmac
import json
import uuid
from typing import TYPE_CHECKING, Any

import structlog
from aiohttp import web

from phantom.conductor.queue import Job
from phantom.exceptions import WebhookSignatureError

if TYPE_CHECKING:
    from phantom.conductor.queue import JobQueue

logger = structlog.get_logger()

DEFAULT_WEBHOOK_PORT = 9443


def validate_signature(payload: bytes, signature_header: str, secret: str) -> None:
    """Validate the X-Hub-Signature-256 header against the webhook secret.

    Args:
        payload: The raw request body.
        signature_header: The value of X-Hub-Signature-256 header.
        secret: The configured webhook secret.

    Raises:
        WebhookSignatureError: If the signature is invalid.
    """
    if not signature_header:
        raise WebhookSignatureError("Missing X-Hub-Signature-256 header")

    if not signature_header.startswith("sha256="):
        raise WebhookSignatureError("Invalid signature format: must start with 'sha256='")

    expected_sig = hmac.new(
        secret.encode("utf-8"),
        payload,
        hashlib.sha256,
    ).hexdigest()

    received_sig = signature_header[7:]  # strip "sha256="

    if not hmac.compare_digest(expected_sig, received_sig):
        raise WebhookSignatureError("Signature mismatch")


def parse_github_event(
    event_type: str,
    payload: dict[str, Any],
) -> dict[str, Any] | None:
    """Parse a GitHub event payload and extract relevant information.

    Args:
        event_type: The X-GitHub-Event header value.
        payload: The parsed JSON payload.

    Returns:
        Dict with parsed event info, or None if the event should be ignored.
    """
    if event_type == "release" and payload.get("action") == "published":
        release = payload.get("release", {})
        repo = payload.get("repository", {})
        return {
            "event": "release.published",
            "repo": repo.get("full_name", ""),
            "ref": release.get("tag_name", ""),
            "repo_name": repo.get("name", ""),
        }

    if event_type == "workflow_dispatch":
        repo = payload.get("repository", {})
        return {
            "event": "workflow_dispatch",
            "repo": repo.get("full_name", ""),
            "ref": payload.get("ref", ""),
            "repo_name": repo.get("name", ""),
        }

    if event_type == "push":
        repo = payload.get("repository", {})
        ref = payload.get("ref", "")
        # Extract branch name from refs/heads/branch-name
        branch = ref.removeprefix("refs/heads/")
        return {
            "event": "push",
            "repo": repo.get("full_name", ""),
            "ref": branch,
            "repo_name": repo.get("name", ""),
            "head_commit": payload.get("after", ""),
        }

    return None


class WebhookListener:
    """Async HTTP server that handles GitHub webhook events.

    Validates signatures, parses events, and submits jobs to the queue.
    """

    def __init__(
        self,
        queue: JobQueue,
        webhook_secret: str,
        port: int = DEFAULT_WEBHOOK_PORT,
        manifest_map: dict[str, str] | None = None,
        allowed_branches: set[str] | None = None,
    ) -> None:
        """Initialize the webhook listener.

        Args:
            queue: The job queue to submit jobs to.
            webhook_secret: Secret for validating GitHub signatures.
            port: Port to listen on (default 9443).
            manifest_map: Mapping of repo_name -> manifest_path.
            allowed_branches: Set of branches that trigger jobs on push events.
        """
        self._queue = queue
        self._secret = webhook_secret
        self._port = port
        self._manifest_map = manifest_map or {}
        self._allowed_branches = allowed_branches or {"main", "master"}
        self._app: web.Application | None = None
        self._runner: web.AppRunner | None = None

    async def start(self) -> None:
        """Start the webhook HTTP server."""
        self._app = web.Application()
        self._app.router.add_post("/webhook/github", self._handle_webhook)
        self._app.router.add_get("/health", self._handle_health)

        self._runner = web.AppRunner(self._app)
        await self._runner.setup()
        site = web.TCPSite(self._runner, "0.0.0.0", self._port)
        await site.start()
        logger.info("webhook_listener_started", port=self._port)

    async def stop(self) -> None:
        """Stop the webhook HTTP server."""
        if self._runner:
            await self._runner.cleanup()
            logger.info("webhook_listener_stopped")

    async def _handle_health(self, request: web.Request) -> web.Response:
        """Health check endpoint."""
        return web.json_response({"status": "ok", "queue_size": self._queue.size})

    async def _handle_webhook(self, request: web.Request) -> web.Response:
        """Handle incoming GitHub webhook requests."""
        body = await request.read()

        # Validate signature
        signature = request.headers.get("X-Hub-Signature-256", "")
        try:
            validate_signature(body, signature, self._secret)
        except WebhookSignatureError as e:
            logger.warning("webhook_signature_rejected", error=str(e))
            return web.json_response(
                {"error": "Invalid signature"},
                status=403,
            )

        # Parse event
        event_type = request.headers.get("X-GitHub-Event", "")
        delivery_id = request.headers.get("X-GitHub-Delivery", "")

        logger.info(
            "webhook_received",
            event_type=event_type,
            delivery_id=delivery_id,
        )

        try:
            payload = json.loads(body)
        except json.JSONDecodeError:
            logger.warning("webhook_invalid_json")
            return web.json_response({"error": "Invalid JSON"}, status=400)

        parsed = parse_github_event(event_type, payload)
        if parsed is None:
            logger.info("webhook_event_ignored", event_type=event_type)
            return web.json_response({"status": "ignored"})

        # For push events, check if the branch is allowed
        if parsed["event"] == "push" and parsed["ref"] not in self._allowed_branches:
            logger.info(
                "webhook_push_branch_ignored",
                branch=parsed["ref"],
                allowed=list(self._allowed_branches),
            )
            return web.json_response({"status": "ignored", "reason": "branch not configured"})

        # Look up manifest for this repo
        repo_name = parsed.get("repo_name", "")
        manifest_path = self._manifest_map.get(repo_name, "")
        if not manifest_path:
            logger.warning(
                "webhook_no_manifest",
                repo=repo_name,
                known_repos=list(self._manifest_map.keys()),
            )
            return web.json_response(
                {"error": f"No manifest configured for repo '{repo_name}'"},
                status=404,
            )

        # Create job
        job = Job(
            job_id=str(uuid.uuid4()),
            project=repo_name,
            manifest_path=manifest_path,
            trigger_source="webhook",
            ref=parsed.get("ref"),
            event_type=parsed["event"],
            if_changed=parsed["event"] == "push",
        )

        try:
            self._queue.submit(job)
        except Exception as e:
            logger.error("webhook_job_submit_failed", error=str(e))
            return web.json_response({"error": str(e)}, status=503)

        logger.info(
            "webhook_job_dispatched",
            job_id=job.job_id,
            project=repo_name,
            event_type=parsed["event"],
            ref=parsed.get("ref"),
        )

        return web.json_response(
            {
                "status": "accepted",
                "job_id": job.job_id,
            }
        )
