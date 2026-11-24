# FlowPilot

Reads business contacts from Word/PDF documents, queues them, schedules calls at a
configurable interval (default 15 min, working hours only) into a text file, syncs that
schedule to Google Calendar, and handles call outcomes (reschedule, not interested,
book a meeting).

## Setup

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
python -m flowpilot
```

Settings live in `config.toml`.
