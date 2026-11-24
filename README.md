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

## Google Calendar setup (one time)

1. Open <https://console.cloud.google.com/> and create a project (e.g. "FlowPilot").
2. **APIs & Services → Library** → search "Google Calendar API" → **Enable**.
3. **APIs & Services → OAuth consent screen** → User type **External** → fill in the
   app name and your email → on **Test users**, add your own Google account.
4. **APIs & Services → Credentials → Create credentials → OAuth client ID** →
   Application type **Desktop app** → **Create** → **Download JSON**.
5. Save the downloaded file in the project folder as `credentials.json`.
6. Run `python -m flowpilot.calendar_sync`. A browser window opens once to sign in;
   the resulting `token.json` is reused afterwards.

`credentials.json` and `token.json` are secrets and are git-ignored.

## Calendar sync process

```bash
python -m flowpilot.calendar_sync           # sync new schedule entries once
python -m flowpilot.calendar_sync --watch   # keep running, check every 30 s
```
