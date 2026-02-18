"""Phantom exception hierarchy.

All Phantom-specific exceptions inherit from PhantomError.
Each subsystem has its own exception subtree for targeted catching.
"""


class PhantomError(Exception):
    """Base exception for all Phantom errors."""


# ── Manifest ──────────────────────────────────────────


class ManifestError(PhantomError):
    """Base for manifest-related errors."""


class ManifestNotFoundError(ManifestError):
    """Manifest file does not exist at the expected path."""


class ManifestValidationError(ManifestError):
    """Manifest fails schema validation."""

    def __init__(self, errors: list[str]) -> None:
        self.errors = errors
        summary = "; ".join(errors[:5])
        if len(errors) > 5:
            summary += f" (+{len(errors) - 5} more)"
        super().__init__(f"Manifest validation failed: {summary}")


# ── Runner ────────────────────────────────────────────


class RunnerError(PhantomError):
    """Base for runner-related errors."""


class RunnerSetupError(RunnerError):
    """Runner failed during build/setup phase."""


class RunnerLaunchError(RunnerError):
    """Application failed to start or become ready."""


class RunnerCaptureError(RunnerError):
    """A capture attempt failed."""


class RunnerTimeoutError(RunnerError):
    """Runner exceeded its total time budget."""


class RequirementError(RunnerError):
    """A system requirement (node, cargo, etc.) is not met."""


# ── Conductor ─────────────────────────────────────────


class ConductorError(PhantomError):
    """Base for conductor/orchestration errors."""


class LockError(ConductorError):
    """Could not acquire the run lock (another instance is running)."""


class WorkspaceError(ConductorError):
    """Workspace creation, cleanup, or clone failure."""


class FixtureError(ConductorError):
    """A fixture failed to execute."""


# ── Darkroom ──────────────────────────────────────────


class DarkroomError(PhantomError):
    """Base for image processing errors."""


class DarkroomStageError(DarkroomError):
    """A specific pipeline stage failed."""

    def __init__(self, stage: str, message: str) -> None:
        self.stage = stage
        super().__init__(f"Darkroom stage '{stage}' failed: {message}")


# ── Publisher ─────────────────────────────────────────


class PublisherError(PhantomError):
    """Base for publishing errors."""


class GitOperationError(PublisherError):
    """A git command failed."""


class PushConflictError(PublisherError):
    """Git push was rejected due to a conflict."""


# ── Webhook / Queue / Scheduler ──────────────────────


class WebhookError(PhantomError):
    """Base for webhook-related errors."""


class WebhookSignatureError(WebhookError):
    """Webhook signature validation failed."""


class QueueError(ConductorError):
    """Job queue is full or encountered an error."""


class SchedulerError(ConductorError):
    """Scheduler encountered an error."""


# ── Analyst ──────────────────────────────────────────


class AnalystError(PhantomError):
    """Base for AI analyst errors."""


class AnalystBudgetExceeded(AnalystError):
    """An API call would exceed the configured budget."""


class AnalystDependencyError(AnalystError):
    """The anthropic package is not installed."""
