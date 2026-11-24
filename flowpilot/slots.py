"""Pure time-slot calculation: given a time, find the next valid call slot.

No files, no queue, no clock - just datetimes in and out, so every rule
(rounding, working hours, weekends) is easy to test.
"""

from __future__ import annotations

from datetime import datetime, timedelta

from flowpilot.config import Config


def round_up(t: datetime, interval_minutes: int) -> datetime:
    """Round up to the next multiple of the interval, e.g. 10:07 -> 10:15."""
    t = t.replace(second=0, microsecond=0) + (
        timedelta(minutes=1) if (t.second or t.microsecond) else timedelta()
    )
    minutes = t.hour * 60 + t.minute
    remainder = minutes % interval_minutes
    if remainder:
        t += timedelta(minutes=interval_minutes - remainder)
    return t


def fit_to_working_hours(t: datetime, cfg: Config) -> datetime:
    """Return t if a call starting at t fits in working hours, else the next start of a working day."""
    t = t.astimezone(cfg.timezone)
    duration = timedelta(minutes=cfg.call_duration_minutes)
    for _ in range(14):  # at most two weeks ahead - guards against an endless loop
        day_start = datetime.combine(t.date(), cfg.working_hours_start, tzinfo=cfg.timezone)
        day_end = datetime.combine(t.date(), cfg.working_hours_end, tzinfo=cfg.timezone)
        if t.weekday() in cfg.working_days:
            if t < day_start:
                t = day_start
            if t + duration <= day_end:
                return t
        # Doesn't fit today: try the start of the next day.
        next_day = t.date() + timedelta(days=1)
        t = datetime.combine(next_day, cfg.working_hours_start, tzinfo=cfg.timezone)
    raise RuntimeError("No working slot found in the next 14 days - check config")


def next_slot(now: datetime, last_slot: datetime | None, cfg: Config) -> datetime:
    """The next call slot: not in the past, at least one interval after the last booked slot."""
    interval = timedelta(minutes=cfg.call_interval_minutes)
    candidate = round_up(now.astimezone(cfg.timezone), cfg.call_interval_minutes)
    if last_slot is not None:
        candidate = max(candidate, last_slot.astimezone(cfg.timezone) + interval)
    return fit_to_working_hours(candidate, cfg)
