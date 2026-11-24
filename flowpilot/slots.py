"""Pure time-slot calculation: given a time, find the next valid call slot.

No files, no queue, no clock - just datetimes in and out, so every rule
(rounding, working hours, weekends, clashes) is easy to test.
"""

from __future__ import annotations

from collections.abc import Iterable
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


def next_free_slot(earliest: datetime, taken: Iterable[datetime], cfg: Config) -> datetime:
    """First slot at or after `earliest` that is in working hours and at least one
    interval away from every already-taken slot."""
    interval = timedelta(minutes=cfg.call_interval_minutes)
    taken = [t.astimezone(cfg.timezone) for t in taken]
    candidate = fit_to_working_hours(
        round_up(earliest.astimezone(cfg.timezone), cfg.call_interval_minutes), cfg
    )
    for _ in range(10_000):  # safety limit
        clashes = [t for t in taken if abs(candidate - t) < interval]
        if not clashes:
            return candidate
        candidate = fit_to_working_hours(max(clashes) + interval, cfg)
    raise RuntimeError("Could not find a free slot")
