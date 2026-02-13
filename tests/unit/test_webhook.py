"""Unit tests for the GitHub webhook listener."""

from __future__ import annotations

import hashlib
import hmac

import pytest

from phantom.conductor.triggers import parse_github_event, validate_signature
from phantom.exceptions import WebhookSignatureError


class TestValidateSignature:
    def _sign(self, payload: bytes, secret: str) -> str:
        sig = hmac.new(secret.encode(), payload, hashlib.sha256).hexdigest()
        return f"sha256={sig}"

    def test_valid_signature(self) -> None:
        payload = b'{"action": "published"}'
        secret = "test-secret"
        sig = self._sign(payload, secret)
        # Should not raise
        validate_signature(payload, sig, secret)

    def test_invalid_signature(self) -> None:
        payload = b'{"action": "published"}'
        secret = "test-secret"
        wrong_sig = "sha256=0000000000000000000000000000000000000000000000000000000000000000"
        with pytest.raises(WebhookSignatureError, match="Signature mismatch"):
            validate_signature(payload, wrong_sig, secret)

    def test_missing_signature(self) -> None:
        payload = b'{"action": "published"}'
        with pytest.raises(WebhookSignatureError, match="Missing"):
            validate_signature(payload, "", "secret")

    def test_invalid_format(self) -> None:
        payload = b'{"action": "published"}'
        with pytest.raises(WebhookSignatureError, match="Invalid signature format"):
            validate_signature(payload, "md5=abc123", "secret")

    def test_different_payloads_different_sigs(self) -> None:
        secret = "test-secret"
        payload1 = b'{"key": "value1"}'
        payload2 = b'{"key": "value2"}'
        sig1 = self._sign(payload1, secret)
        sig2 = self._sign(payload2, secret)
        assert sig1 != sig2

        # Cross-validation should fail
        with pytest.raises(WebhookSignatureError):
            validate_signature(payload1, sig2, secret)


class TestParseGitHubEvent:
    def test_release_published(self) -> None:
        payload = {
            "action": "published",
            "release": {"tag_name": "v1.0.0"},
            "repository": {"full_name": "org/repo", "name": "repo"},
        }
        result = parse_github_event("release", payload)
        assert result is not None
        assert result["event"] == "release.published"
        assert result["repo"] == "org/repo"
        assert result["ref"] == "v1.0.0"
        assert result["repo_name"] == "repo"

    def test_release_created_ignored(self) -> None:
        payload = {
            "action": "created",
            "release": {"tag_name": "v1.0.0"},
            "repository": {"full_name": "org/repo", "name": "repo"},
        }
        result = parse_github_event("release", payload)
        assert result is None

    def test_workflow_dispatch(self) -> None:
        payload = {
            "ref": "refs/heads/main",
            "repository": {"full_name": "org/repo", "name": "repo"},
        }
        result = parse_github_event("workflow_dispatch", payload)
        assert result is not None
        assert result["event"] == "workflow_dispatch"
        assert result["ref"] == "refs/heads/main"

    def test_push_event(self) -> None:
        payload = {
            "ref": "refs/heads/main",
            "after": "abc123def456",
            "repository": {"full_name": "org/repo", "name": "repo"},
        }
        result = parse_github_event("push", payload)
        assert result is not None
        assert result["event"] == "push"
        assert result["ref"] == "main"  # Branch name extracted
        assert result["head_commit"] == "abc123def456"

    def test_push_strips_refs_prefix(self) -> None:
        payload = {
            "ref": "refs/heads/feature/my-branch",
            "after": "abc123",
            "repository": {"full_name": "org/repo", "name": "repo"},
        }
        result = parse_github_event("push", payload)
        assert result is not None
        assert result["ref"] == "feature/my-branch"

    def test_ignored_event_type(self) -> None:
        result = parse_github_event("issues", {"action": "opened"})
        assert result is None

    def test_ignored_ping_event(self) -> None:
        result = parse_github_event("ping", {"zen": "Responsive is better than fast."})
        assert result is None
