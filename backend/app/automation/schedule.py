"""Cron schedule helpers for scheduled automations.

Schedule config lives in ``Automation.config_json`` as
``{"cron": "<expr>", "timezone": "<IANA tz>"}``. ``next_run_at`` is always stored
as an aware UTC instant; cron evaluation happens in the automation's timezone.
"""

from __future__ import annotations

from datetime import UTC, datetime
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from croniter import croniter

_DEFAULT_TIMEZONE = "UTC"


class InvalidScheduleError(ValueError):
    """Raised when a schedule automation's cron/timezone config is invalid."""


def parse_schedule(config_json: dict | None) -> tuple[str, str]:
    """Return ``(cron_expr, timezone)`` from config_json, validating both.

    Raises InvalidScheduleError when the cron expression or timezone is missing
    or invalid.
    """
    cfg = config_json or {}
    cron_expr = cfg.get("cron")
    if not cron_expr or not isinstance(cron_expr, str):
        raise InvalidScheduleError(
            "schedule automation requires config_json.cron (a cron expression)."
        )
    if not croniter.is_valid(cron_expr):
        raise InvalidScheduleError(f"Invalid cron expression: {cron_expr!r}.")
    tz_name = cfg.get("timezone") or _DEFAULT_TIMEZONE
    if not isinstance(tz_name, str):
        raise InvalidScheduleError("config_json.timezone must be a string IANA timezone.")
    try:
        ZoneInfo(tz_name)
    except (ZoneInfoNotFoundError, ValueError) as exc:
        raise InvalidScheduleError(f"Invalid timezone: {tz_name!r}.") from exc
    return cron_expr, tz_name


def compute_next_run_at(config_json: dict | None, *, after: datetime) -> datetime:
    """Compute the next due UTC instant strictly after ``after`` for the schedule.

    ``after`` is treated as UTC (made aware if naive). Returns an aware UTC datetime.
    """
    cron_expr, tz_name = parse_schedule(config_json)
    if after.tzinfo is None:
        after = after.replace(tzinfo=UTC)
    local_base = after.astimezone(ZoneInfo(tz_name))
    nxt_local = croniter(cron_expr, local_base).get_next(datetime)
    return nxt_local.astimezone(UTC)
