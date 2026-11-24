"""Loads settings from config.toml into a typed, validated object."""

from __future__ import annotations

import tomllib
from dataclasses import dataclass
from datetime import time
from pathlib import Path
from zoneinfo import ZoneInfo

PROJECT_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_CONFIG_PATH = PROJECT_ROOT / "config.toml"


@dataclass(frozen=True)
class Config:
    call_interval_minutes: int
    call_duration_minutes: int
    working_hours_start: time
    working_hours_end: time
    working_days: tuple[int, ...]
    timezone: ZoneInfo
    default_country_code: str
    queue_db: Path
    schedule_file: Path
    contacts_store: Path
    calendar_id: str
    credentials_file: Path
    token_file: Path


def _parse_hhmm(value: str, field: str) -> time:
    try:
        return time.fromisoformat(value)
    except ValueError:
        raise ValueError(f"{field} must be HH:MM, got {value!r}") from None


def load_config(path: Path = DEFAULT_CONFIG_PATH) -> Config:
    with open(path, "rb") as f:
        raw = tomllib.load(f)

    sched = raw["scheduling"]
    paths = raw["paths"]
    google = raw["google"]

    cfg = Config(
        call_interval_minutes=int(sched["call_interval_minutes"]),
        call_duration_minutes=int(sched["call_duration_minutes"]),
        working_hours_start=_parse_hhmm(sched["working_hours_start"], "working_hours_start"),
        working_hours_end=_parse_hhmm(sched["working_hours_end"], "working_hours_end"),
        working_days=tuple(sched["working_days"]),
        timezone=ZoneInfo(sched["timezone"]),
        default_country_code=raw["extraction"]["default_country_code"],
        # Relative paths are resolved from the project root, so scripts work
        # no matter which folder they are started from.
        queue_db=PROJECT_ROOT / paths["queue_db"],
        schedule_file=PROJECT_ROOT / paths["schedule_file"],
        contacts_store=PROJECT_ROOT / paths["contacts_store"],
        calendar_id=google["calendar_id"],
        credentials_file=PROJECT_ROOT / google["credentials_file"],
        token_file=PROJECT_ROOT / google["token_file"],
    )
    _validate(cfg)
    return cfg


def _validate(cfg: Config) -> None:
    if cfg.call_interval_minutes <= 0:
        raise ValueError("call_interval_minutes must be positive")
    if cfg.call_duration_minutes <= 0:
        raise ValueError("call_duration_minutes must be positive")
    if cfg.working_hours_start >= cfg.working_hours_end:
        raise ValueError("working_hours_start must be before working_hours_end")
    if not cfg.working_days or any(d not in range(7) for d in cfg.working_days):
        raise ValueError("working_days must be a non-empty list of numbers 0-6")
    code = cfg.default_country_code
    if not (code.startswith("+") and code[1:].isdigit()):
        raise ValueError(f"default_country_code must look like +94, got {code!r}")
