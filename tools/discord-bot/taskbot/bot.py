"""The Discord side: slash commands, Done buttons and the weekly schedule."""

from __future__ import annotations

import asyncio
import logging
import re
import time as clock
from datetime import date, datetime, timedelta
from zoneinfo import ZoneInfo

import discord
from discord import app_commands
from discord.ext import tasks

from .config import Settings
from .planner import WeeklyPlan, build_plan, current_week
from .sheet import Member, Task, TaskTable, is_everyone, match_member, parse_date, people_for
from .store import Calendar, SheetStore, UnsafeWriteError

SHEET_BUSY = (
    "⚠️ Google Sheets didn't answer in time, so I'm not sure this saved. "
    "Check with `/tasks` in a minute and try again if it's still open."
)

log = logging.getLogger(__name__)

MAX_MESSAGE = 1900
BUTTONS_PER_MESSAGE = 25

STATUS_MARKS = {
    "done": "✅",
    "in progress": "🔄",
    "blocked": "🚧",
    "postponed": "⏸️",
    "cancelled": "✖️",
}

# How a status change reads in the WORK LOG's "Status / result" column.
LOG_STATUS = {
    "done": "Done",
    "in progress": "In progress",
    "blocked": "Blocked",
    "postponed": "Postponed",
    "cancelled": "Decision made",
    "not started": "Postponed",
}


# -- formatting ------------------------------------------------------------------


def who(names: list[str], team: list[Member]) -> str:
    if not names:
        return "*unassigned*"
    out = []
    for name in names:
        if is_everyone(name):
            out.append("everyone")
            continue
        m = match_member(name, team)
        out.append(f"<@{m.discord_id}>" if m and m.discord_id else name)
    return ", ".join(out)


def task_line(t: Task, team: list[Member] | None = None) -> str:
    mark = STATUS_MARKS.get(t.status.strip().casefold(), "▫️")
    parts = [f"{mark} `{t.id}` {t.title}"]
    if t.due:
        parts.append(f"due {t.due}")
    if t.priority.casefold() == "critical":
        parts.append("**critical**")
    if team is not None:
        parts.append(who(t.assignees, team))
    return " · ".join(parts)


def chunks(lines: list[str], limit: int = MAX_MESSAGE) -> list[str]:
    out, current = [], ""
    for line in lines:
        if current and len(current) + len(line) + 1 > limit:
            out.append(current)
            current = ""
        current = f"{current}\n{line}" if current else line
    if current:
        out.append(current)
    return out


def weekly_summary(
    plan: WeeklyPlan,
    team: list[Member],
    total: int,
    done: int,
    cal: Calendar | None = None,
    today: date | None = None,
) -> list[str]:
    week = cal.week(plan.week) if cal else None
    span = f" ({week.start:%d %b} to {week.end:%d %b})" if week else ""
    lines = [f"## 📡 Week {plan.week}{span}"]
    if week and week.focus:
        lines.append(f"**Focus:** {week.focus}")
    pct = round(100 * done / total) if total else 0
    lines.append(f"Project progress: **{done}/{total}** tasks done ({pct}%).")
    if cal and today:
        nxt = next(
            (
                m
                for m in sorted(cal.milestones, key=lambda m: m.target or date.max)
                if m.target and m.target >= today and m.status.casefold() != "done"
            ),
            None,
        )
        if nxt:
            lines.append(f"Next gate: **{nxt.gate}** on {nxt.target:%d %b}: {nxt.title}")
    if plan.done_last_week:
        lines.append(f"Finished last week: {len(plan.done_last_week)} 🎉")
    if plan.carried_over:
        lines.append("\n**Past their target finish, still open**")
        lines += [task_line(t, team) for t in plan.carried_over]
    if plan.this_week:
        lines.append(f"\n**Scheduled for week {plan.week}**")
        lines += [task_line(t, team) for t in plan.this_week]
    if not plan.open_tasks:
        lines.append("\nNothing open this week. Nice work.")
    if plan.new_assignments:
        lines.append(
            "\n*Tasks with no owner were shared out to whoever had the least on. "
            "Swap with `/assign` if that doesn't suit.*"
        )
    lines.append(
        "\nSign off with the buttons in your DMs, or `/done`. Use `/status` for anything else."
    )
    return lines


# -- buttons ---------------------------------------------------------------------


class DoneButton(
    discord.ui.DynamicItem[discord.ui.Button], template=r"taskbot:done:(?P<id>[\w-]+)"
):
    """A "Mark done" button that keeps working after the bot restarts."""

    def __init__(self, task_id: str, title: str = "") -> None:
        label = f"Done: {task_id}" + (f" {title}" if title else "")
        super().__init__(
            discord.ui.Button(
                label=label[:80],
                style=discord.ButtonStyle.success,
                custom_id=f"taskbot:done:{task_id}",
            )
        )
        self.task_id = task_id

    @classmethod
    async def from_custom_id(cls, interaction, item, match: re.Match[str], /):  # noqa: ANN001
        return cls(match["id"])

    async def callback(self, interaction: discord.Interaction) -> None:
        bot: TaskBot = interaction.client  # type: ignore[assignment]
        await interaction.response.defer(ephemeral=True, thinking=True)
        try:
            message = await bot.sign_off(self.task_id, interaction.user)
        except Exception:
            log.exception("Sign-off of %s failed", self.task_id)
            message = SHEET_BUSY
        await interaction.followup.send(message, ephemeral=True)
        if not message.startswith("✅") or interaction.message is None:
            return
        try:
            view = discord.ui.View.from_message(interaction.message, timeout=None)
            for child in view.children:
                if getattr(child, "custom_id", None) == self.item.custom_id:
                    child.disabled = True
                    child.label = f"Signed off: {self.task_id}"
            await interaction.message.edit(view=view)
        except discord.HTTPException:
            pass


def done_views(tasks_: list[Task]) -> list[discord.ui.View]:
    views = []
    for i in range(0, len(tasks_), BUTTONS_PER_MESSAGE):
        view = discord.ui.View(timeout=None)
        for t in tasks_[i : i + BUTTONS_PER_MESSAGE]:
            view.add_item(DoneButton(t.id, t.title[:40]))
        views.append(view)
    return views


# -- the bot ---------------------------------------------------------------------


class TaskBot(discord.Client):
    def __init__(self, settings: Settings, store: SheetStore) -> None:
        super().__init__(intents=discord.Intents.default())
        self.settings = settings
        self.store = store
        self.tz = ZoneInfo(settings.timezone)
        self.tree = app_commands.CommandTree(self)
        self.lock = asyncio.Lock()
        self._cache: tuple[float, TaskTable, list[Member], Calendar] | None = None
        register_commands(self)

    # -- lifecycle

    async def setup_hook(self) -> None:
        self.add_dynamic_items(DoneButton)
        if self.settings.guild_id:
            guild = discord.Object(id=self.settings.guild_id)
            self.tree.copy_global_to(guild=guild)
            await self.tree.sync(guild=guild)
        else:
            await self.tree.sync()
        at = self.settings.weekly_time.replace(tzinfo=self.tz)
        self.daily = tasks.loop(time=at)(self._daily_tick)
        self.daily.start()

    async def on_ready(self) -> None:
        log.info("Logged in as %s", self.user)

    async def _daily_tick(self) -> None:
        today = datetime.now(self.tz).weekday()
        try:
            if today == self.settings.weekly_day:
                await self.run_weekly()
            elif today == self.settings.reminder_day:
                await self.remind()
        except Exception:
            log.exception("Scheduled run failed")

    # -- sheet access

    async def load(self, fresh: bool = True) -> tuple[TaskTable, list[Member], Calendar]:
        if not fresh and self._cache and clock.monotonic() - self._cache[0] < 60:
            return self._cache[1], self._cache[2], self._cache[3]
        cal = await asyncio.to_thread(self.store.load_calendar)
        start = self.settings.project_start or cal.start
        table = await asyncio.to_thread(self.store.load_tasks, start)
        names = [n for t in table.tasks for n in t.assignees]
        team = await asyncio.to_thread(self.store.load_team, names)
        self._cache = (clock.monotonic(), table, team, cal)
        return table, team, cal

    def today(self) -> date:
        return datetime.now(self.tz).date()

    def week_now(self, table: TaskTable, cal: Calendar) -> int:
        open_tasks = [t for t in table.tasks if not t.is_done(self.settings.done_values)]
        start = self.settings.project_start or cal.start
        return current_week(self.today(), start, open_tasks)

    def week_start(self, cal: Calendar) -> date | None:
        start = self.settings.project_start or cal.start
        if start is None:
            return None
        weeks = max(0, (self.today() - start).days // 7)
        return start + timedelta(weeks=weeks)

    def plan(self, table: TaskTable, team: list[Member], cal: Calendar, week: int | None = None,
             auto_assign: bool = True) -> WeeklyPlan:  # fmt: skip
        return build_plan(
            table.tasks,
            week or self.week_now(table, cal),
            team,
            self.settings.done_values,
            self.settings.closed_values,
            auto_assign=auto_assign,
        )

    async def channel(self) -> discord.abc.Messageable:
        ch = self.get_channel(self.settings.channel_id)
        return ch or await self.fetch_channel(self.settings.channel_id)

    def member_name(self, team: list[Member], user: discord.abc.User) -> str:
        me = next((m for m in team if m.discord_id == user.id), None)
        return me.name if me else user.display_name

    async def announce(self, text: str) -> None:
        try:
            ch = await self.channel()
            await ch.send(text, allowed_mentions=discord.AllowedMentions.none())
        except discord.HTTPException:
            log.warning("Couldn't post to the channel")

    # -- actions

    async def set_status(
        self, task_id: str, user: discord.abc.User, status: str, note: str = ""
    ) -> tuple[Task | None, str]:
        """Change a task's status in the Sheet and add a WORK LOG row. Returns (task, error)."""
        try:
            return await self._set_status(task_id, user, status, note)
        except Exception:
            # e.g. Google's rate limit outlasting the retries: answer instead of spinning
            log.exception("Couldn't change %s", task_id)
            self._cache = None
            return None, SHEET_BUSY

    async def _set_status(
        self, task_id: str, user: discord.abc.User, status: str, note: str
    ) -> tuple[Task | None, str]:
        async with self.lock:
            table, team, cal = await self.load()
            task = table.find(task_id)
            if task is None:
                return None, f"I couldn't find task `{task_id}` in the plan."
            done = status.casefold() in self.settings.done_values
            if done and task.is_done(self.settings.done_values):
                return None, f"`{task.id}` is already marked done."
            by = self.member_name(team, user)
            today = self.today().isoformat()
            changes = {"status": status, "last_updated": today}
            if done:
                changes |= {"signed_off_at": today, "signed_off_by": by}
            if note:
                changes["progress"] = f"{note} ({by}, {self.today():%d %b})"
            try:
                await asyncio.to_thread(self.store.update_task, task.id, changes, task.title)
            except UnsafeWriteError as exc:
                log.warning("Refused a write to %s: %s", task.id, exc)
                return None, f"⚠️ I didn't change the Sheet: {exc}"
            action = "Signed off in Discord" if done else f"Status set to {status} in Discord"
            try:
                await asyncio.to_thread(
                    self.store.log,
                    self.today(),
                    self.week_start(cal),
                    task,
                    action,
                    by,
                    LOG_STATUS.get(status.casefold(), status),
                    note,
                )
            except (UnsafeWriteError, LookupError) as exc:
                log.warning("Couldn't add a WORK LOG row for %s: %s", task.id, exc)
            except Exception:
                # The status is already saved; say so rather than reporting a failure.
                log.exception("Couldn't add a WORK LOG row for %s", task.id)
            self._cache = None
            task.status = status
        return task, ""

    async def sign_off(self, task_id: str, user: discord.abc.User, note: str = "") -> str:
        task, error = await self.set_status(task_id, user, self.settings.done_label, note)
        if task is None:
            return error
        extra = f"\n> {note}" if note else ""
        await self.announce(
            f"✅ **{user.display_name}** signed off `{task.id}` {task.title}{extra}"
        )
        return f"✅ Signed off `{task.id}` {task.title}. The Sheet and WORK LOG are updated."

    async def change_status(
        self, task_id: str, user: discord.abc.User, status: str, note: str = ""
    ) -> str:
        if status.casefold() in self.settings.done_values:
            return await self.sign_off(task_id, user, note)
        task, error = await self.set_status(task_id, user, status, note)
        if task is None:
            return error
        mark = STATUS_MARKS.get(status.casefold(), "▫️")
        if status.casefold() in ("blocked", "postponed", "cancelled"):
            extra = f"\n> {note}" if note else ""
            await self.announce(
                f"{mark} **{user.display_name}** set `{task.id}` {task.title} to {status}{extra}"
            )
        return f"{mark} `{task.id}` is now **{status}**."

    async def assign(self, task_id: str, member: discord.abc.User, by: discord.abc.User) -> str:
        async with self.lock:
            table, team, cal = await self.load()
            task = table.find(task_id)
            if task is None:
                return f"I couldn't find task `{task_id}` in the plan."
            m = next((x for x in team if x.discord_id == member.id), None)
            if m is None:
                return (
                    f"{member.display_name} isn't linked to a name in the TEAM tab yet. "
                    "They can run `/link` first."
                )
            try:
                await asyncio.to_thread(
                    self.store.update_task,
                    task.id,
                    {"assignee": m.name, "last_updated": self.today().isoformat()},
                    task.title,
                )
            except UnsafeWriteError as exc:
                return f"⚠️ I didn't change the Sheet: {exc}"
            await asyncio.to_thread(
                self.store.log,
                self.today(),
                self.week_start(cal),
                task,
                f"Owner changed to {m.name} in Discord",
                self.member_name(team, by),
                "Decision made",
            )
            self._cache = None
        try:
            await member.send(
                f"📌 You've been given `{task.id}` {task.title}.", view=done_views([task])[0]
            )
        except discord.HTTPException:
            pass
        return f"📌 `{task.id}` {task.title} is now with {m.name}."

    async def run_weekly(self, week: int | None = None) -> WeeklyPlan:
        async with self.lock:
            table, team, cal = await self.load()
            plan = self.plan(table, team, cal, week)
            titles = {t.id: t.title for t in table.tasks}
            await asyncio.to_thread(self.store.assign_many, plan.new_assignments, titles)
            for task_id, names in plan.new_assignments.items():
                t = table.find(task_id)
                if t is not None:
                    await asyncio.to_thread(
                        self.store.log,
                        self.today(),
                        self.week_start(cal),
                        t,
                        f"Assigned to {', '.join(names)} by the Discord bot",
                        "Discord bot",
                        "Decision made",
                    )
            await asyncio.to_thread(self._fill_last_week, table, cal, plan)
            self._cache = None

        done = sum(t.is_done(self.settings.done_values) for t in table.tasks)
        ch = await self.channel()
        summary = weekly_summary(plan, team, len(table.tasks), done, cal, self.today())
        for text in chunks(summary):
            await ch.send(text)

        failed = await self._dm_everyone(plan, team, f"Your tasks for week {plan.week}")
        notes = []
        if plan.unmatched_names:
            notes.append(
                "These owners in the plan aren't linked to anyone on Discord yet: "
                + ", ".join(sorted(plan.unmatched_names))
                + ". Run `/link` to connect yourself."
            )
        if failed:
            notes.append("I couldn't DM " + ", ".join(failed) + " (DMs closed?).")
        if notes:
            await ch.send("\n".join(notes), allowed_mentions=discord.AllowedMentions.none())
        return plan

    def _fill_last_week(self, table: TaskTable, cal: Calendar, plan: WeeklyPlan) -> None:
        """Write last week's finished and slipped task IDs into WEEKLY CHECK-IN, if blank."""
        last = cal.week(plan.week - 1)
        if last is None:
            return
        finished = [
            t.id
            for t in table.tasks
            if t.is_done(self.settings.done_values)
            and (d := parse_date(t.signed_off_at, self.settings.day_first))
            and last.start <= d <= last.end
        ]
        moved = [
            t.id
            for t in table.tasks
            if not t.is_done(self.settings.done_values)
            and not t.is_closed(self.settings.closed_values)
            and t.finish
            and last.start <= t.finish <= last.end
        ]
        try:
            self.store.fill_checkin(
                last.number,
                "Done: " + ", ".join(finished) if finished else "",
                "Still open: " + ", ".join(moved) if moved else "",
            )
        except Exception:
            log.exception("Couldn't update the weekly check-in")

    async def remind(self) -> None:
        table, team, cal = await self.load()
        plan = self.plan(table, team, cal, auto_assign=False)
        await self._dm_everyone(plan, team, f"Reminder: still open for week {plan.week}")

    async def _dm_everyone(self, plan: WeeklyPlan, team: list[Member], heading: str) -> list[str]:
        failed = []
        by_member = plan.by_member(team)
        for m in team:
            items = by_member.get(m.name)
            if not items or m.discord_id is None:
                continue
            try:
                user = self.get_user(m.discord_id) or await self.fetch_user(m.discord_id)
                lines = [f"**{heading}**"] + [task_line(t) for t in items]
                for text in chunks(lines):
                    await user.send(text)
                for view in done_views(items):
                    await user.send("Press a button when it's done:", view=view)
            except discord.HTTPException:
                failed.append(m.name)
        return failed


# -- slash commands --------------------------------------------------------------


def register_commands(bot: TaskBot) -> None:
    tree = bot.tree

    @tree.error
    async def on_command_error(
        interaction: discord.Interaction, error: app_commands.AppCommandError
    ) -> None:
        log.error("/%s failed", getattr(interaction.command, "name", "?"), exc_info=error)
        try:
            if interaction.response.is_done():
                await interaction.followup.send(SHEET_BUSY, ephemeral=True)
            else:
                await interaction.response.send_message(SHEET_BUSY, ephemeral=True)
        except discord.HTTPException:
            pass

    async def task_choices(interaction: discord.Interaction, current: str):  # noqa: ANN202
        table, _, _ = await bot.load(fresh=False)
        key = current.casefold()
        hits = [t for t in table.tasks if key in t.id.casefold() or key in t.title.casefold()]
        hits.sort(key=lambda t: t.is_done(bot.settings.done_values))
        return [
            app_commands.Choice(name=f"{t.id} · {t.title}"[:100], value=t.id) for t in hits[:25]
        ]

    async def name_choices(interaction: discord.Interaction, current: str):  # noqa: ANN202
        table, team, _ = await bot.load(fresh=False)
        names = {m.name for m in team} | {
            n for t in table.tasks for n in t.assignees if not is_everyone(n)
        }
        key = current.casefold()
        return [app_commands.Choice(name=n, value=n) for n in sorted(names) if key in n.casefold()][
            :25
        ]

    async def status_choices(interaction: discord.Interaction, current: str):  # noqa: ANN202
        key = current.casefold()
        return [
            app_commands.Choice(name=s, value=s)
            for s in bot.settings.status_values
            if key in s.casefold()
        ]

    @tree.command(name="tasks", description="Show your open tasks (or someone else's)")
    @app_commands.describe(member="Whose tasks to show")
    async def tasks_cmd(interaction: discord.Interaction, member: discord.Member | None = None):
        await interaction.response.defer(ephemeral=True)
        target = member or interaction.user
        table, team, cal = await bot.load()
        m = next((x for x in team if x.discord_id == target.id), None)
        if m is None:
            await interaction.followup.send(
                f"{target.display_name} isn't linked to a name in the plan yet. Use `/link`.",
                ephemeral=True,
            )
            return
        s = bot.settings
        week = bot.week_now(table, cal)
        mine = [
            t
            for t in table.tasks
            if not t.is_done(s.done_values)
            and not t.is_closed(s.closed_values)
            and m in people_for(t.assignees, team)
        ]
        if not mine:
            await interaction.followup.send(f"{m.name} has no open tasks. 🎉", ephemeral=True)
            return
        now_ = [t for t in mine if t.week is None or t.week <= week]
        later = [t for t in mine if t not in now_]
        lines = [f"**Open tasks for {m.name}** (it's week {week})"]
        lines += [task_line(t) for t in now_] or ["Nothing due yet."]
        if later:
            lines.append("\n*Coming up*")
            lines += [f"{task_line(t)} · starts week {t.week}" for t in later[:15]]
        for text in chunks(lines):
            await interaction.followup.send(text, ephemeral=True)
        if target == interaction.user and now_:
            await interaction.followup.send(
                "Sign off here:", view=done_views(now_)[0], ephemeral=True
            )

    @tree.command(name="week", description="Show every task in a week and who has it")
    @app_commands.describe(number="Week number (defaults to this week)")
    async def week_cmd(interaction: discord.Interaction, number: int | None = None):
        await interaction.response.defer()
        table, team, cal = await bot.load()
        week = number or bot.week_now(table, cal)
        items = [t for t in table.tasks if t.active_in(week)]
        info = cal.week(week)
        head = f"**Week {week}**" + (f" ({info.start:%d %b} to {info.end:%d %b})" if info else "")
        if info and info.focus:
            head += f"\nFocus: {info.focus}"
        if not items:
            await interaction.followup.send(f"{head}\nThere's nothing scheduled.")
            return
        lines = [head] + [task_line(t, team) for t in items]
        for text in chunks(lines):
            await interaction.followup.send(text, allowed_mentions=discord.AllowedMentions.none())

    @tree.command(name="done", description="Sign off a task as finished")
    @app_commands.describe(task="The task to sign off", note="What was done, or a link")
    @app_commands.autocomplete(task=task_choices)
    async def done_cmd(interaction: discord.Interaction, task: str, note: str = ""):
        await interaction.response.defer(ephemeral=True, thinking=True)
        await interaction.followup.send(
            await bot.sign_off(task, interaction.user, note[:300]), ephemeral=True
        )

    @tree.command(name="status", description="Set a task to In progress, Blocked, Postponed…")
    @app_commands.describe(task="The task", status="New status", note="Why, or what changed")
    @app_commands.autocomplete(task=task_choices, status=status_choices)
    async def status_cmd(interaction: discord.Interaction, task: str, status: str, note: str = ""):
        await interaction.response.defer(ephemeral=True, thinking=True)
        allowed = {s.casefold(): s for s in bot.settings.status_values}
        if status.casefold() not in allowed:
            await interaction.followup.send(
                "Pick one of: " + ", ".join(bot.settings.status_values), ephemeral=True
            )
            return
        await interaction.followup.send(
            await bot.change_status(task, interaction.user, allowed[status.casefold()], note[:300]),
            ephemeral=True,
        )

    @tree.command(name="assign", description="Give a task to someone")
    @app_commands.autocomplete(task=task_choices)
    async def assign_cmd(interaction: discord.Interaction, task: str, member: discord.Member):
        await interaction.response.defer(thinking=True)
        await interaction.followup.send(
            await bot.assign(task, member, interaction.user),
            allowed_mentions=discord.AllowedMentions.none(),
        )

    @tree.command(name="link", description="Connect your Discord account to your name in the plan")
    @app_commands.describe(name="Your name as it's written in the plan")
    @app_commands.autocomplete(name=name_choices)
    async def link_cmd(interaction: discord.Interaction, name: str):
        await interaction.response.defer(ephemeral=True)
        name = name.strip()[:60]
        async with bot.lock:
            m = await asyncio.to_thread(bot.store.link_member, name, interaction.user.id)
            bot._cache = None
        await interaction.followup.send(
            f"Linked you to **{m.name}**. You'll get your tasks by DM each week.", ephemeral=True
        )

    @tree.command(name="progress", description="How much of each week is done")
    async def progress_cmd(interaction: discord.Interaction):
        await interaction.response.defer()
        table, _, cal = await bot.load()
        done_values = bot.settings.done_values
        week_now = bot.week_now(table, cal)
        weeks: dict[int, list[Task]] = {}
        for t in table.tasks:
            if t.week is not None and not t.is_closed(bot.settings.closed_values):
                weeks.setdefault(t.week_end or t.week, []).append(t)
        lines = [f"**Progress by target finish week** (it's week {week_now})"]
        for w in sorted(weeks):
            items = weeks[w]
            done = sum(t.is_done(done_values) for t in items)
            filled = round(10 * done / len(items))
            bar = "█" * filled + "░" * (10 - filled)
            flag = " ⚠️" if w < week_now and done < len(items) else ""
            lines.append(f"`W{w:02d}` {bar} {done}/{len(items)}{flag}")
        for text in chunks(lines):
            await interaction.followup.send(text)

    @tree.command(name="plan", description="Post and hand out this week's tasks now")
    @app_commands.describe(week="Week number (defaults to this week)")
    @app_commands.default_permissions(manage_guild=True)
    async def plan_cmd(interaction: discord.Interaction, week: int | None = None):
        await interaction.response.defer(ephemeral=True, thinking=True)
        plan = await bot.run_weekly(week)
        await interaction.followup.send(
            f"Posted week {plan.week}: {len(plan.open_tasks)} open tasks, "
            f"{len(plan.new_assignments)} newly assigned.",
            ephemeral=True,
        )
