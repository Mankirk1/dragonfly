# Dragonfly task bot

A Discord bot that runs the team's plan from the **Radar Detection Timeline** Google Sheet (in the Proposal Documents folder).

- **Every Saturday** (the plan's weeks run Saturday to Friday; day and time are configurable) it works out the project week from the WEEKLY CHECK-IN tab, then posts in your team channel: that week's focus, the next milestone gate, every open task whose target dates fall in the week, and anything past its target finish that isn't done. Each person gets a DM with their own list and ✅ buttons. Tasks owned by "All" go to everyone.
- **Every Wednesday** it DMs a reminder of what each person still has open.
- **Signing off** a task (the ✅ button or `/done`) sets its Status to Done, fills in Completion date and Last updated, adds your note to "What changed / actual progress", and adds a new row to the WORK LOG. Nothing in the log is ever overwritten.
- `/status` sets In progress, Blocked or Postponed the same way. Blocked and postponed tasks are announced so the team sees them.
- At the start of each week it fills in last week's "What we actually completed" and "Work moved / new week" in WEEKLY CHECK-IN, but only if those cells are still blank.

The Sheet stays the source of truth. Edit it by hand whenever you like, for example moving a task's target dates when work slips, and the bot picks up the change on its next read.

## Commands

| Command | What it does |
| --- | --- |
| `/link name` | Connect your Discord account to your name in the plan. Everyone does this once. |
| `/tasks [member]` | Your open tasks (or someone else's), with sign-off buttons. |
| `/week [number]` | Everything scheduled in a week, its focus, and who has what. |
| `/done task [note]` | Mark a task Done. Type part of the ID or name to search. The note goes into the progress column and the WORK LOG. |
| `/status task status [note]` | Set Not started, In progress, Blocked, Postponed, Done or Cancelled. |
| `/assign task member` | Change a task's owner. They get a DM. |
| `/progress` | Done/total grouped by target finish week, with late weeks flagged. |
| `/plan [week]` | Post and hand out a week's tasks now (needs Manage Server). |

## How it reads the Sheet

**TASK BOARD**: the bot uses the first tab that has a task column and a week or date column, so it skips START HERE. It finds the header row (row 4) under the title rows and reads these columns by name:

| Column | Used for |
| --- | --- |
| ID | Task IDs in Discord (`R05`). New rows without an ID get the next one (`R39`). |
| Planned task | The task name |
| Owner(s) | Who gets the task. `Ana + Ben` is two people; `All` is everyone. |
| Target start / Target finish | Which weeks the task is scheduled in, and when it counts as late |
| Status | Not started / In progress / Blocked / Postponed / Done / Cancelled. Cancelled tasks are left out. |
| Priority | Critical tasks are flagged |
| What changed / actual progress | Notes from `/done` and `/status` are added here |
| Last updated, Completion date | Set when a task changes or is signed off |

**WEEKLY CHECK-IN** sets the week numbers (W01 starts 14 Nov 2026) and each week's focus. **MILESTONES** gives the "next gate" line. **WORK LOG** gets one new row per sign-off, status change or owner change, filled in as Date, Week beginning, Member, Related task ID, the task, what was done, and Status / result.

The bot adds one new tab, **TEAM**, with `Name` and `Discord ID`. It's seeded with the owner names from the plan, and `/link` fills in the IDs. It doesn't add or move any columns on the TASK BOARD.

### Keeping the Sheet safe

The bot only ever edits these cells, and every edit is checked first:

- **On the TASK BOARD**, only Status, Owner(s), What changed / actual progress, Last updated and Completion date, and only on the one task's row. It never edits the ID, task name, dates, priority or any other column, and never adds, deletes, moves or sorts rows or columns.
- **Before each edit** it re-reads the Sheet, finds the task by its ID, and stops if that ID is on more than one row or the row no longer holds the same task (for example if someone moved rows in the meantime).
- **It never overwrites a formula**, never blanks a filled cell, and only writes Status values from the dropdown. Progress notes are added after what's there, never replacing it.
- **After each edit** it re-reads the row to check it still belongs to the same task.
- **New WORK LOG rows** go below everything else, skipping rows that only look empty because of a formula. Old entries are never touched.
- **WEEKLY CHECK-IN** cells are only filled when they're blank.
- **Text typed in Discord** can't become a formula.
- Every edit is a single cell, so nothing next to it can be cleared.

When a check fails the bot changes nothing and tells the person why in Discord. For a first test, set `TASKBOT_READ_ONLY=true`: the bot reads the Sheet and posts as normal, but only logs the edits it would have made.

Other layouts work too: column and tab names are detected from common headers (Week, Task, Owner, Status, Due…) and can be set in `.env`.

## Setup

You need three things. None of them ever go in git.

### 1. A Discord bot

1. Go to <https://discord.com/developers/applications> → **New Application** → name it.
2. **Bot** tab → **Reset Token** → copy it. That's `TASKBOT_DISCORD_TOKEN`. No privileged intents are needed.
3. **OAuth2 → URL Generator**: tick `bot` and `applications.commands`, then the permissions **Send Messages**, **Embed Links** and **Read Message History**. Open the URL and add the bot to your server.
4. In Discord turn on **Settings → Advanced → Developer Mode**, then right-click your server → **Copy Server ID** (`TASKBOT_GUILD_ID`) and the channel for announcements → **Copy Channel ID** (`TASKBOT_CHANNEL_ID`).

### 2. A Google service account

1. In <https://console.cloud.google.com/> create a project (or use one you have).
2. **APIs & Services → Library**: enable **Google Sheets API** and **Google Drive API**.
3. **IAM & Admin → Service Accounts → Create**. No roles needed. Open it → **Keys → Add key → JSON**. A `.json` file downloads.
4. Open the Sheet → **Share** → paste the service account's email (`…@….iam.gserviceaccount.com`) → **Editor**.
5. Copy the Sheet's link: that's `TASKBOT_SHEET_ID` (the full link works).

The Sheet belongs to a groupmate, so its owner (or anyone with edit access who can share) needs to add the service account as an Editor.

### 3. Run it

```bash
cd tools/discord-bot
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env            # fill it in
mkdir -p secrets && mv ~/Downloads/your-key.json secrets/service-account.json
python -m taskbot
```

Then in Discord each groupmate runs `/link`, and you run `/plan` once to see this week's post. Tip: do the first run with `TASKBOT_READ_ONLY=true` and check the log before letting it write.

The bot reads which week it is from the WEEKLY CHECK-IN tab. If that tab ever goes away, set `TASKBOT_PROJECT_START` to the first day of week 1.

## Hosting it for free

The bot needs to be running all the time, but it's tiny (about 60 MB of RAM, no inbound ports).

**Recommended: Google Cloud's always-free e2-micro VM.** You already have a Google Cloud project from step 2, and one e2-micro in `us-central1`, `us-west1` or `us-east1` with a 30 GB standard disk is free each month (Google asks for a card on file but doesn't charge within the free tier).

1. **Compute Engine → VM instances → Create**: e2-micro, region `us-central1`, Debian, standard persistent disk.
2. SSH in from the console, then:

   ```bash
   sudo apt-get update && sudo apt-get install -y python3-venv git
   sudo useradd --system --create-home taskbot
   sudo git clone https://github.com/Mankirk1/dragonfly.git /opt/dragonfly
   cd /opt/dragonfly/tools/discord-bot
   sudo python3 -m venv .venv && sudo .venv/bin/pip install -r requirements.txt
   sudo nano .env                      # paste your settings
   sudo mkdir secrets && sudo nano secrets/service-account.json
   sudo chown -R taskbot: . && sudo chmod 600 .env secrets/*
   sudo cp dragonfly-taskbot.service /etc/systemd/system/
   sudo systemctl enable --now dragonfly-taskbot
   journalctl -u dragonfly-taskbot -f  # watch the logs
   ```

3. To update later: `cd /opt/dragonfly && sudo git pull && sudo systemctl restart dragonfly-taskbot`.

Other options that work: Oracle Cloud's always-free VMs (same steps), a Raspberry Pi or a spare laptop at home, or anything that runs the included `Dockerfile` (`docker run --env-file .env -v $PWD/secrets:/app/secrets:ro …`). Avoid free "web service" tiers that sleep when idle: the bot would go offline.

## Development

```bash
pip install -r requirements.txt pytest
python -m pytest
```

The planning and Sheet logic (`sheet.py`, `planner.py`, `store.py`) is tested against an in-memory fake of the Sheet, so tests don't need Discord or Google.
