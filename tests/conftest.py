"""Shared test helpers."""

import dataclasses
from datetime import datetime

import pytest

from flowpilot.config import load_config


@pytest.fixture
def cfg(tmp_path):
    """Real config.toml values, but all files go to a temporary folder."""
    real = load_config()
    return dataclasses.replace(
        real,
        queue_db=tmp_path / "queue.db",
        schedule_file=tmp_path / "schedule.txt",
        contacts_store=tmp_path / "contacts.json",
    )


@pytest.fixture
def at(cfg):
    """at(2026, 11, 24, 10, 7) -> that local time in the configured timezone."""
    def make(*args):
        return datetime(*args, tzinfo=cfg.timezone)
    return make
