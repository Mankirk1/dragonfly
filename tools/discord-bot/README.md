# Dragonfly task bot

A Discord bot that runs the team's plan from the **Radar Detection Timeline** Google Sheet (in the Proposal Documents folder).

- **Every Saturday** (the plan's weeks run Saturday to Friday; day and time are configurable) it works out the project week from the WEEKLY CHECK-IN tab, then posts in your team channel:
  - **Last week in brief:** what was signed off, what was due and is still open, and what's in progress or blocked.
  - **Focus for this week:** the WEEKLY CHECK-IN focus, the three tasks to do first (overdue, then critical, then soonest), any missed milestone, and the next milestone gate with how many open tasks are due before it.
  - Every open task whose target dates fall in the week, and anything past its target finish that isn't done.

  Both summaries are built only from what's in the Sheet.

  Each person gets a DM with their own list and ✅ buttons. Tasks owned by "All" go to everyone.
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

When a check fails the bot changes nothing and tells the person why in Discord. For a first test, set `TASKBOT_READ_ONLY=true`: the bot reads the Sheet and posts as normal, but only logs the edits it would have made to the plan. It still creates and fills its own TEAM tab, so `/link` and DMs work during the test.

Other layouts work too: column and tab names are detected from common headers (Week, Task, Owner, Status, Due…) and can be set in `.env`.

## Setup

The bot runs on Google Cloud's always-free e2-micro VM. It needs no key files and stores no passwords on the VM:

- It signs in to Google as the VM's own **service account**, a bot identity with no project roles. The only thing it can open is the Sheet you share with it, plus one secret.
- The **Discord token** lives in Google **Secret Manager**. The bot reads it into memory at start-up, so it is never written to disk or into `.env`.
- The VM has **no SSH open to the internet**. You connect through Google's Identity-Aware Proxy (IAP) using your Google sign-in.
- The bot runs as an unprivileged `taskbot` user, sandboxed by systemd (`dragonfly-taskbot.service`), and can't change its own code or settings.

Turn on 2-step verification for the Google and Discord accounts you use, since they control the bot.

### 1. Make the Discord bot

1. Go to <https://discord.com/developers/applications> → **New Application** → name it.
2. **Bot** tab:
   - Turn **Public Bot** off, so only you can add it to servers.
   - Leave every privileged intent off.
   - Don't copy the token yet.
3. **OAuth2 → URL Generator**:
   - Tick `bot` and `applications.commands`.
   - Tick only **Send Messages**, **Embed Links** and **Read Message History**.
   - Open the URL and add the bot to your server.
4. In Discord, turn on **Settings → Advanced → Developer Mode**. Then copy two IDs and keep them for later:
   - Right-click the server → **Copy Server ID**: that's `TASKBOT_GUILD_ID`.
   - Right-click the announcements channel → **Copy Channel ID**: that's `TASKBOT_CHANNEL_ID`.

### 2. Set up Google Cloud (in Cloud Shell)

Open <https://console.cloud.google.com/>, pick or create a project, and click the **Activate Cloud Shell** (`>_`) icon at the top right. Run each block below in Cloud Shell.

**Choose the project and turn on the APIs.** Replace `YOUR_PROJECT_ID` with your project's ID:

```bash
gcloud config set project YOUR_PROJECT_ID
PROJECT=$(gcloud config get-value project)
SA="taskbot@${PROJECT}.iam.gserviceaccount.com"
ZONE=us-central1-a
gcloud services enable compute.googleapis.com sheets.googleapis.com \
  secretmanager.googleapis.com iap.googleapis.com
```

**Create the bot's identity.** It gets no roles on the project:

```bash
gcloud iam service-accounts create taskbot --display-name="Dragonfly task bot"
echo "$SA"   # the Sheet gets shared with this address in step 3
```

**Store the Discord token in Secret Manager.**

1. Discord Developer Portal → **Bot** → **Reset Token** → copy it.
2. Run this, paste the token when asked, and press Enter. Nothing shows on screen and nothing is saved in your shell history.

```bash
read -rsp "Discord bot token: " TOKEN; echo
printf %s "$TOKEN" | gcloud secrets create discord-token \
  --replication-policy=automatic --data-file=-
unset TOKEN
gcloud secrets add-iam-policy-binding discord-token \
  --member="serviceAccount:${SA}" --role=roles/secretmanager.secretAccessor
```

The last command lets the bot read this one secret and nothing else.

**Make a private network.** It only lets in SSH that comes through Google's IAP:

```bash
gcloud compute networks create taskbot-net --subnet-mode=custom
gcloud compute networks subnets create taskbot-subnet --network=taskbot-net \
  --region=us-central1 --range=10.10.0.0/24
gcloud compute firewall-rules create taskbot-allow-iap-ssh --network=taskbot-net \
  --direction=INGRESS --allow=tcp:22 --source-ranges=35.235.240.0/20
```

**Create the VM with the bot's identity attached.** The Sheets scope plus the service account's own lack of roles is what limits it:

```bash
gcloud compute instances create taskbot --zone="$ZONE" --machine-type=e2-micro \
  --subnet=taskbot-subnet --image-family=debian-12 --image-project=debian-cloud \
  --boot-disk-size=30GB --boot-disk-type=pd-standard \
  --service-account="$SA" \
  --scopes=https://www.googleapis.com/auth/spreadsheets,https://www.googleapis.com/auth/cloud-platform \
  --shielded-secure-boot --shielded-vtpm --shielded-integrity-monitoring \
  --metadata=enable-oslogin=TRUE,block-project-ssh-keys=TRUE
```

One e2-micro in `us-central1` with a 30 GB standard disk is in Google's always-free tier. Google asks for a card on file.

### 3. Share the Sheet with the bot

The Sheet's owner, or anyone who can share it, does this:

1. Open the "Radar Detection Timeline" Sheet → **Share**.
2. Paste the `taskbot@….iam.gserviceaccount.com` address from step 2.
3. Choose **Editor** and untick **Notify people**.
4. Copy the Sheet's link: that's `TASKBOT_SHEET_ID`.

Share only this Sheet. The bot can't see anything else in anyone's Drive.

### 4. Install the bot on the VM

**Connect to the VM** from Cloud Shell:

```bash
gcloud compute ssh taskbot --zone=us-central1-a --tunnel-through-iap
```

**Install the bot.** On the VM, run:

```bash
sudo apt-get update && sudo apt-get install -y python3-venv git
sudo useradd --system --no-create-home --shell /usr/sbin/nologin taskbot
sudo git clone https://github.com/Mankirk1/dragonfly.git /opt/dragonfly
cd /opt/dragonfly/tools/discord-bot
sudo python3 -m venv .venv && sudo .venv/bin/pip install -r requirements.txt
sudo cp .env.example .env
sudo nano .env
```

The code stays owned by root, so the bot can read it but can't change it.

**Fill in `.env`.**

- `TASKBOT_DISCORD_TOKEN_SECRET=projects/YOUR_PROJECT_ID/secrets/discord-token/versions/latest`
- `TASKBOT_GUILD_ID` and `TASKBOT_CHANNEL_ID` from step 1.
- `TASKBOT_SHEET_ID`: the Sheet link from step 3.
- `TASKBOT_READ_ONLY=true` for the first run.
- Leave `TASKBOT_DISCORD_TOKEN` empty.

Save with Ctrl+O, Enter, then Ctrl+X. Then lock the file:

```bash
sudo chown root:taskbot .env && sudo chmod 640 .env
```

### 5. Test in read-only mode, then go live

**Start the bot and watch its log:**

```bash
sudo cp dragonfly-taskbot.service /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable --now dragonfly-taskbot
sudo journalctl -u dragonfly-taskbot -f
```

You should see `Read 38 tasks from the plan`, and the bot shows as online in Discord. Press Ctrl+C to stop watching.

**Try it in Discord.** In read-only mode the bot posts and replies normally, but it only logs the edits it would make to the plan.

- Each groupmate runs `/link`.
- You run `/plan` and `/tasks`.
- Check the `would write` lines in the log.

**Go live.** When the planned edits look right, run:

```bash
sudo sed -i 's/^TASKBOT_READ_ONLY=.*/TASKBOT_READ_ONLY=false/' .env
sudo systemctl restart dragonfly-taskbot
```

### Looking after it

- **Update the bot:**

  ```bash
  cd /opt/dragonfly && sudo git pull && sudo systemctl restart dragonfly-taskbot
  ```

- **Change the Discord token** (if it leaks, or just now and then):
  1. Discord → **Bot** → **Reset Token**. The old token stops working at once.
  2. In Cloud Shell, store the new one:

     ```bash
     read -rsp "Discord bot token: " TOKEN; echo
     printf %s "$TOKEN" | gcloud secrets versions add discord-token --data-file=-
     unset TOKEN
     ```

  3. On the VM, run `sudo systemctl restart dragonfly-taskbot`.
- **Turn off the bot's Sheet access** at any time: remove the `taskbot@…` address from the Sheet's **Share** list.
- **Week numbering:** the bot reads which week it is from the WEEKLY CHECK-IN tab. If that tab ever goes away, set `TASKBOT_PROJECT_START` to the first day of week 1.

### Running it on your own computer

For development, put the token itself in `TASKBOT_DISCORD_TOKEN` in a local `.env` and run `chmod 600 .env`.

For Google sign-in, run `gcloud auth application-default login`. This signs in as you, so use a Sheet copy you own.

Service account key files (`TASKBOT_GOOGLE_CREDENTIALS_FILE`) are still read if set, but they're long-lived passwords and many accounts block them. Use the VM above instead.

## Development

```bash
pip install -r requirements.txt pytest
python -m pytest
```

The planning and Sheet logic (`sheet.py`, `planner.py`, `store.py`) is tested against an in-memory fake of the Sheet, so tests don't need Discord or Google.
