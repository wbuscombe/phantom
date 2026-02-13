"""Unit tests for the cron scheduler."""

from __future__ import annotations

from datetime import UTC, datetime

from phantom.conductor.scheduler import ScheduleEntry, Scheduler


class TestScheduleEntry:
    def test_default_if_changed(self) -> None:
        entry = ScheduleEntry(
            project="test",
            manifest_path="/tmp/test.yml",
            cron_expression="0 * * * *",
        )
        assert entry.if_changed is True


class TestScheduler:
    def test_add_valid_entry(self) -> None:
        from phantom.conductor.queue import JobQueue

        queue = JobQueue(max_depth=5)
        scheduler = Scheduler(queue=queue)

        entry = ScheduleEntry(
            project="test",
            manifest_path="/tmp/test.yml",
            cron_expression="0 * * * *",
        )
        scheduler.add_entry(entry)
        assert scheduler.entry_count == 1

    def test_add_invalid_cron_rejected(self) -> None:
        from phantom.conductor.queue import JobQueue

        queue = JobQueue(max_depth=5)
        scheduler = Scheduler(queue=queue)

        entry = ScheduleEntry(
            project="test",
            manifest_path="/tmp/test.yml",
            cron_expression="not-valid-cron",
        )
        scheduler.add_entry(entry)
        # Invalid cron should be rejected — not added
        assert scheduler.entry_count == 0

    def test_get_next_run(self) -> None:
        base = datetime(2024, 1, 15, 10, 0, 0, tzinfo=UTC)
        next_run = Scheduler.get_next_run("0 * * * *", base)
        assert next_run.hour == 11
        assert next_run.minute == 0

    def test_get_next_run_every_5_minutes(self) -> None:
        base = datetime(2024, 1, 15, 10, 3, 0, tzinfo=UTC)
        next_run = Scheduler.get_next_run("*/5 * * * *", base)
        assert next_run.minute == 5

    def test_get_next_run_daily_at_midnight(self) -> None:
        base = datetime(2024, 1, 15, 10, 0, 0, tzinfo=UTC)
        next_run = Scheduler.get_next_run("0 0 * * *", base)
        assert next_run.day == 16
        assert next_run.hour == 0

    def test_is_due_first_check(self) -> None:
        from phantom.conductor.queue import JobQueue

        queue = JobQueue(max_depth=5)
        scheduler = Scheduler(queue=queue)

        entry = ScheduleEntry(
            project="test",
            manifest_path="/tmp/test.yml",
            cron_expression="* * * * *",  # Every minute
        )

        # With every-minute cron, it should be due
        now = datetime.now(tz=UTC)
        assert scheduler._is_due(entry, now) is True

    def test_is_due_not_yet(self) -> None:
        from phantom.conductor.queue import JobQueue

        queue = JobQueue(max_depth=5)
        scheduler = Scheduler(queue=queue)

        entry = ScheduleEntry(
            project="test",
            manifest_path="/tmp/test.yml",
            cron_expression="0 0 1 1 *",  # Jan 1 at midnight — unlikely to be now
        )

        now = datetime(2024, 6, 15, 12, 0, 0, tzinfo=UTC)
        # Last check was very recently
        scheduler._last_check["test"] = now
        assert scheduler._is_due(entry, now) is False

    def test_add_entries_from_manifests(self) -> None:
        from phantom.conductor.queue import JobQueue

        queue = JobQueue(max_depth=5)
        scheduler = Scheduler(queue=queue)

        configs = [
            {"project": "a", "manifest_path": "/tmp/a.yml", "cron": "0 * * * *"},
            {"project": "b", "manifest_path": "/tmp/b.yml", "cron": "*/30 * * * *"},
        ]
        scheduler.add_entries_from_manifests(configs)
        assert scheduler.entry_count == 2
