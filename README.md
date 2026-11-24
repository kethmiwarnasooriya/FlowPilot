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
python -m flowpilot --help
```

Settings live in `config.toml` (interval, working hours, timezone, file paths).

## Google Calendar setup (one time)

1. Open <https://console.cloud.google.com/> and create a project (e.g. "FlowPilot").
2. **APIs & Services → Library** → search "Google Calendar API" → **Enable**.
3. **APIs & Services → OAuth consent screen** → User type **External** → fill in the
   app name and your email → on **Test users**, add your own Google account.
4. **APIs & Services → Credentials → Create credentials → OAuth client ID** →
   Application type **Desktop app** → **Create** → **Download JSON**.
5. Save the downloaded file in the project folder as `credentials.json`.
6. Run `python -m flowpilot sync`. A browser window opens once to sign in;
   the resulting `token.json` is reused afterwards.

`credentials.json` and `token.json` are secrets and are git-ignored.

## Usage

```bash
# 1. Read documents; business contacts are saved and queued
python -m flowpilot ingest samples/contacts.docx samples/contacts.pdf

# 2. Scheduler: give each queued contact a call slot in data/schedule.txt
python -m flowpilot schedule

# 3. Calendar sync: create a Google Calendar event for each new schedule entry
python -m flowpilot sync

# See contacts and their status
python -m flowpilot list
python -m flowpilot list --status not_interested
python -m flowpilot show <contact-id>
```

### Recording call outcomes (admin)

```bash
# Asked to be called again later
python -m flowpilot callback <contact-id> --in "2 weeks" --remark "Busy until year-end"

# Not interested (add --do-not-call if they asked never to be called again)
python -m flowpilot not-interested <contact-id> --remark "Already has a supplier"

# Interested: book a physical meeting
python -m flowpilot meeting <contact-id> --at "2026-12-02 14:00" --location "Their office" --remark "Wants a demo"
```

Callbacks go back through the queue, so run `schedule` (and then `sync`) afterwards.

### Running as background processes

The scheduler and the calendar sync are independent processes connected only by the
schedule file. Run each in its own terminal to keep them going:

```bash
python -m flowpilot schedule --watch
python -m flowpilot sync --watch
```

## Tests

```bash
python -m pytest
```
