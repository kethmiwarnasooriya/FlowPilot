"""Shared test helpers."""

import dataclasses
from datetime import datetime
from pathlib import Path

import pytest

from flowpilot.config import load_config
from flowpilot.contact_store import ContactStore


@pytest.fixture
def cfg(tmp_path):
    """Real config.toml values, but EVERY file path points into a temporary folder,
    so tests can never touch real data - including paths added to Config later."""
    real = load_config()
    redirected = {
        f.name: tmp_path / getattr(real, f.name).name
        for f in dataclasses.fields(real)
        if isinstance(getattr(real, f.name), Path)
    }
    return dataclasses.replace(real, **redirected)


@pytest.fixture
def store(cfg):
    s = ContactStore(cfg.contacts_store)
    yield s
    s.close()


@pytest.fixture
def at(cfg):
    """at(2026, 11, 24, 10, 7) -> that local time in the configured timezone."""
    def make(*args):
        return datetime(*args, tzinfo=cfg.timezone)
    return make
