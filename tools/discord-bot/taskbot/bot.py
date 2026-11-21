"""The Discord side: slash commands, Done buttons and the weekly schedule."""

from __future__ import annotations

import asyncio
import logging
import re
import time as clock
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from zoneinfo import ZoneInfo

import discord
from discord import app_commands
from discord.ext import tasks

from .access import may_change
from .config import Settings
from .digest import focus, gate_heads_up, recap
from .planner import WeeklyPlan, build_plan, current_week
from .sheet import (
    Member,
    Task,
    TaskTable,
    clean_link,
    is_everyone,
    match_member,
    parse_date,
    people_for,
)
from .store import Calendar, SheetStore, UnsafeWriteError

SHEET_BUSY = (
    "⚠️ Google Sheets didn't answer in time, so I'm not sure this saved. "
    "Check with `/tasks` in a minute and try again if it's still open."
)

log = logging.getLogger(__name__)

BAD_LINK = (
    "⚠️ The evidence link must be one http(s) link, like https://drive.google.com/… "
    "Nothing was changed."
)
UNDO_SECONDS = 10 * 60
HEALTH_MINUTES = 10
ALERT_AFTER_SECONDS = 30 * 60
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


def _short(text: str, limit: int = 120) -> str:
    text = " ".join(text.split())
    return text if len(text) <= limit else text[: limit - 1] + "…"


def task_details(t: Task) -> list[str]:
    """What "done" looks like and what comes next, from the plan, as indented lines."""
    out = []
    if t.expected:
        out.append(f"   ↳ Done means: {_short(t.expected)}")
    if t.next_action:
        out.append(f"   ↳ Next: {_short(t.next_action)}")
    return out


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
    tasks: list[Task],
    settings: Settings,
    cal: Calendar | None = None,
    today: date | None = None,
) -> list[str]:
    week = cal.week(plan.week) if cal else None
    span = f" ({week.start:%d %b} to {week.end:%d %b})" if week else ""
    done = sum(t.is_done(settings.done_values) for t in tasks)
    pct = round(100 * done / len(tasks)) if tasks else 0
    lines = [
        f"## 📡 Week {plan.week}{span}",
        f"Project progress: **{done}/{len(tasks)}** tasks done ({pct}%).",
    ]
    last = cal.week(plan.week - 1) if cal else None
    brief = recap(tasks, last, settings.done_values, settings.closed_values, settings.day_first)
    if brief:
        lines += ["", *brief]
    lines += [""] + focus(
        plan,
        week,
        cal.milestones if cal else [],
        today or date.today(),
        lambda t: who(t.assignees, team),
        [
            t
            for t in tasks
            if not t.is_done(settings.done_values) and not t.is_closed(settings.closed_values)
        ],
    )
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
    """A "Mark done" button that keeps working after the bot restarts.

    Pressing it opens a short form (what was done, an evidence link) before anything
    is written, so a stray tap changes nothing.
    """

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
        await interaction.response.send_modal(
            SignOffForm(self.task_id, interaction.message, self.item.custom_id or "")
        )


class SignOffForm(discord.ui.Modal):
    what: discord.ui.TextInput = discord.ui.TextInput(
        label="What was done?",
        style=discord.TextStyle.paragraph,
        required=False,
        max_length=300,
        placeholder="e.g. Ordered both sensors; the quote is in the BOM",
    )
    link: discord.ui.TextInput = discord.ui.TextInput(
        label="Evidence link (optional)",
        required=False,
        max_length=300,
        placeholder="https://…",
    )

    def __init__(
        self, task_id: str, source: discord.Message | None = None, custom_id: str = ""
    ) -> None:
        super().__init__(title=f"Sign off {task_id}"[:45], timeout=15 * 60)
        self.task_id = task_id
        self.source = source
        self.custom_id_ = custom_id

    async def on_submit(self, interaction: discord.Interaction) -> None:
        bot: TaskBot = interaction.client  # type: ignore[assignment]
        link = clean_link(self.link.value or "")
        if link is None:
            await interaction.response.send_message(BAD_LINK, ephemeral=True)
            return
        await interaction.response.defer(ephemeral=True, thinking=True)
        message, undo = await bot.sign_off(
            self.task_id, interaction.user, (self.what.value or "").strip()[:300], link
        )
        await send_result(interaction, message, undo)
        if undo is not None and self.source is not None:
            await disable_button(self.source, self.custom_id_, f"Signed off: {self.task_id}")

    async def on_error(  # type: ignore[override]
        self, interaction: discord.Interaction, error: Exception, /
    ) -> None:
        log.error("Sign-off form for %s failed", self.task_id, exc_info=error)
        await send_result(interaction, SHEET_BUSY, None)


class UndoButton(
    discord.ui.DynamicItem[discord.ui.Button],
    template=r"taskbot:undo:(?P<id>[\w-]+):(?P<user>\d+):(?P<at>\d+):(?P<prev>\d+):(?P<note>\d+)",
):
    """Undo a sign-off, for the person who made it, within ten minutes."""

    def __init__(self, task_id: str, user_id: int, at: int, prev: int, note: int = 0) -> None:
        super().__init__(
            discord.ui.Button(
                label=f"Undo sign-off of {task_id}"[:80],
                style=discord.ButtonStyle.secondary,
                custom_id=f"taskbot:undo:{task_id}:{user_id}:{at}:{prev}:{note}",
            )
        )
        self.task_id, self.user_id, self.at, self.prev = task_id, user_id, at, prev
        self.note = note  # length of the progress note the sign-off added, to take back

    @classmethod
    async def from_custom_id(cls, interaction, item, match: re.Match[str], /):  # noqa: ANN001
        return cls(
            match["id"],
            int(match["user"]),
            int(match["at"]),
            int(match["prev"]),
            int(match["note"]),
        )

    async def callback(self, interaction: discord.Interaction) -> None:
        bot: TaskBot = interaction.client  # type: ignore[assignment]
        if interaction.user.id != self.user_id:
            await interaction.response.send_message(
                "Only the person who signed it off can undo it.", ephemeral=True
            )
            return
        self.item.disabled = True
        if clock.time() - self.at > UNDO_SECONDS:
            self.item.label = "Undo expired"
            await interaction.response.edit_message(view=self.view)
            await interaction.followup.send(
                "Undo is only open for 10 minutes. Use `/status` to change it now.",
                ephemeral=True,
            )
            return
        self.item.label = "Undone"
        await interaction.response.edit_message(view=self.view)
        message = await bot.undo_sign_off(
            self.task_id, interaction.user, self.prev, self.at, self.note
        )
        if message == SHEET_BUSY:  # nothing changed: let them try again
            self.item.disabled = False
            self.item.label = f"Undo sign-off of {self.task_id}"[:80]
            try:
                await interaction.edit_original_response(view=self.view)
            except discord.HTTPException:
                pass
        await interaction.followup.send(message, ephemeral=True)


async def send_result(
    interaction: discord.Interaction, message: str, view: discord.ui.View | None
) -> None:
    try:
        if not interaction.response.is_done():
            await interaction.response.send_message(message, ephemeral=True)
        elif view is not None:
            await interaction.followup.send(message, view=view, ephemeral=True)
        else:
            await interaction.followup.send(message, ephemeral=True)
    except discord.HTTPException:
        log.warning("Couldn't reply to %s", interaction.user)


async def disable_button(message: discord.Message, custom_id: str, label: str) -> None:
    try:
        view = discord.ui.View.from_message(message, timeout=None)
        for child in view.children:
            if getattr(child, "custom_id", None) == custom_id:
                child.disabled = True  # type: ignore[attr-defined]
                child.label = label[:80]  # type: ignore[attr-defined]
        await message.edit(view=view)
    except discord.HTTPException:
        pass


def undo_view(task_id: str, user_id: int, prev: int, note: int = 0) -> discord.ui.View:
    view = discord.ui.View(timeout=None)
    view.add_item(UndoButton(task_id, user_id, int(clock.time()), prev, note))
    return view


def done_views(tasks_: list[Task]) -> list[discord.ui.View]:
    views = []
    for i in range(0, len(tasks_), BUTTONS_PER_MESSAGE):
        view = discord.ui.View(timeout=None)
        for t in tasks_[i : i + BUTTONS_PER_MESSAGE]:
            view.add_item(DoneButton(t.id, t.title[:40]))
        views.append(view)
    return views


# -- the bot ---------------------------------------------------------------------


@dataclass
class StatusChange:
    task: Task | None
    error: str = ""
    previous: str = ""  # the status before the change
    note: str = ""  # the progress note it added, if any


class TaskBot(discord.Client):
    def __init__(self, settings: Settings, store: SheetStore) -> None:
        super().__init__(intents=discord.Intents.default())
        self.settings = settings
        self.store = store
        self.tz = ZoneInfo(settings.timezone)
        self.tree = app_commands.CommandTree(self)
        self.lock = asyncio.Lock()
        self._cache: tuple[float, TaskTable, list[Member], Calendar] | None = None
        self._down_since: float | None = None  # when the Sheet stopped answering
        self._alerted = False
        register_commands(self)

    # -- lifecycle

    async def setup_hook(self) -> None:
        self.add_dynamic_items(DoneButton, UndoButton)
        if self.settings.guild_id:
            guild = discord.Object(id=self.settings.guild_id)
            self.tree.copy_global_to(guild=guild)
            await self.tree.sync(guild=guild)
        else:
            await self.tree.sync()
        at = self.settings.weekly_time.replace(tzinfo=self.tz)
        self.daily = tasks.loop(time=at)(self._daily_tick)
        self.daily.start()
        self.health = tasks.loop(minutes=HEALTH_MINUTES)(self._health_tick)
        self.health.start()

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
        try:
            await self.gate_notice()
        except Exception:
            log.exception("Milestone heads-up failed")

    async def gate_notice(self) -> None:
        """Post a heads-up a few days before each unfinished milestone gate."""
        if self.settings.gate_notice_days <= 0:
            return
        table, team, cal = await self.load()
        s = self.settings
        open_tasks = [
            t
            for t in table.tasks
            if not t.is_done(s.done_values) and not t.is_closed(s.closed_values)
        ]
        lines = gate_heads_up(
            cal.milestones,
            open_tasks,
            self.today(),
            s.gate_notice_days,
            lambda t: who(t.assignees, team),
        )
        if not lines:
            return
        ch = await self.channel()
        for text in chunks(lines):
            await ch.send(text, allowed_mentions=discord.AllowedMentions.none())

    async def _health_tick(self) -> None:
        """Check the Sheet answers; tell the owner once if it's been down 30 minutes."""
        try:
            await asyncio.to_thread(self.store.ping)
        except Exception as exc:
            now = clock.monotonic()
            if self._down_since is None:
                self._down_since = now
                log.warning("Can't reach the Sheet: %s", type(exc).__name__)
            elif not self._alerted and now - self._down_since >= ALERT_AFTER_SECONDS:
                code = getattr(exc, "code", "")
                self._alerted = await self.alert(
                    "⚠️ I haven't been able to reach the plan Sheet for 30 minutes "
                    f"({type(exc).__name__} {code}). Sign-offs will fail until it's back. "
                    "Check the bot's log on the VM, and that the Sheet is still shared with "
                    "the bot's Google account."
                )
            return
        if self._alerted:
            await self.alert("✅ I can reach the plan Sheet again.")
        self._down_since, self._alerted = None, False

    async def alert(self, text: str) -> bool:
        """DM TASKBOT_ALERT_USER_ID, or the Discord app's owner. True if it was sent."""
        try:
            user_id = self.settings.alert_user_id
            if not user_id:
                app = await self.application_info()
                user_id = (app.team.owner if app.team and app.team.owner else app.owner).id
            user = self.get_user(user_id) or await self.fetch_user(user_id)
            await user.send(text)
            return True
        except (discord.HTTPException, AttributeError):
            log.warning("Couldn't send an alert DM")
            return False

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

    async def is_admin(self, user: discord.abc.User) -> bool:
        """Manage Server permission, or the role in TASKBOT_ADMIN_ROLE, on the bot's server."""
        guild = self.get_guild(self.settings.guild_id) if self.settings.guild_id else None
        if guild is None:
            try:
                guild = getattr(await self.channel(), "guild", None)
            except discord.HTTPException:
                guild = None
        if guild is None:
            return False
        member = guild.get_member(user.id)
        if member is None:
            try:
                member = await guild.fetch_member(user.id)
            except discord.HTTPException:
                return False
        if member.guild_permissions.manage_guild or member.guild_permissions.administrator:
            return True
        role = self.settings.admin_role.strip().casefold()
        return bool(role) and any(
            r.name.casefold() == role or str(r.id) == role for r in member.roles
        )

    async def allowed(self, task: Task, team: list[Member], user: discord.abc.User) -> str:
        """An error message when ``user`` may not change ``task``, or "" when they may."""
        ok, why = may_change(task, team, user.id)
        if ok or await self.is_admin(user):
            return ""
        return f"⛔ {why}"

    async def set_status(
        self,
        task_id: str,
        user: discord.abc.User,
        status: str,
        note: str = "",
        evidence: str = "",
    ) -> StatusChange:
        """Change a task's status in the Sheet and add a WORK LOG row."""
        try:
            return await self._set_status(task_id, user, status, note, evidence)
        except Exception:
            # e.g. Google's rate limit outlasting the retries: answer instead of spinning
            log.exception("Couldn't change %s", task_id)
            self._cache = None
            return StatusChange(None, SHEET_BUSY)

    async def _set_status(
        self, task_id: str, user: discord.abc.User, status: str, note: str, evidence: str
    ) -> StatusChange:
        async with self.lock:
            table, team, cal = await self.load()
            task = table.find(task_id)
            if task is None:
                return StatusChange(None, f"I couldn't find task `{task_id}` in the plan.")
            done = status.casefold() in self.settings.done_values
            if done and task.is_done(self.settings.done_values):
                return StatusChange(None, f"`{task.id}` is already marked done.")
            denied = await self.allowed(task, team, user)
            if denied:
                return StatusChange(None, denied)
            previous = task.status
            by = self.member_name(team, user)
            today = self.today().isoformat()
            changes = {"status": status, "last_updated": today}
            if done:
                changes |= {"signed_off_at": today, "signed_off_by": by}
            detail = " ".join(x for x in (note, evidence) if x)
            progress = f"{detail} ({by}, {self.today():%d %b})" if detail else ""
            if progress:
                changes["progress"] = progress
            try:
                await asyncio.to_thread(self.store.update_task, task.id, changes, task.title)
            except UnsafeWriteError as exc:
                log.warning("Refused a write to %s: %s", task.id, exc)
                return StatusChange(None, f"⚠️ I didn't change the Sheet: {exc}")
            if done:
                action = f"{note} (signed off in Discord)" if note else "Signed off in Discord"
                comment = ""
            else:
                action, comment = f"Status set to {status} in Discord", note
            await self._log(
                cal, task, action, by, LOG_STATUS.get(status.casefold(), status), comment, evidence
            )
            self._cache = None
            task.status = status
        return StatusChange(task, "", previous, progress)

    async def _log(
        self,
        cal: Calendar,
        task: Task,
        action: str,
        by: str,
        status: str,
        note: str = "",
        evidence: str = "",
    ) -> None:
        """Add a WORK LOG row. The task change is already saved, so a failure here is
        logged rather than reported as a failed change."""
        try:
            await asyncio.to_thread(
                self.store.log,
                self.today(),
                self.week_start(cal),
                task,
                action,
                by,
                status,
                note,
                evidence,
            )
        except (UnsafeWriteError, LookupError) as exc:
            log.warning("Couldn't add a WORK LOG row for %s: %s", task.id, exc)
        except Exception:
            log.exception("Couldn't add a WORK LOG row for %s", task.id)

    def _status_code(self, status: str) -> int:
        values = [v.casefold() for v in self.settings.status_values]
        key = status.strip().casefold()
        return values.index(key) if key in values else 0

    async def sign_off(
        self, task_id: str, user: discord.abc.User, note: str = "", evidence: str = ""
    ) -> tuple[str, discord.ui.View | None]:
        """Sign a task off. Returns the reply and, when it worked, an Undo button."""
        change = await self.set_status(task_id, user, self.settings.done_label, note, evidence)
        task = change.task
        if task is None:
            return change.error, None
        extra = f"\n> {note}" if note else ""
        if evidence:
            extra += f"\n> 🔗 <{evidence}>"
        await self.announce(
            f"✅ **{user.display_name}** signed off `{task.id}` {task.title}{extra}"
        )
        return (
            f"✅ Signed off `{task.id}` {task.title}. The Sheet and WORK LOG are updated.\n"
            "Made a mistake? You can undo it for the next 10 minutes.",
            undo_view(task.id, user.id, self._status_code(change.previous), len(change.note)),
        )

    async def undo_sign_off(
        self, task_id: str, user: discord.abc.User, prev: int, at: int, note: int = 0
    ) -> str:
        values = self.settings.status_values
        status = values[prev] if 0 <= prev < len(values) else values[0]
        signed_on = datetime.fromtimestamp(at, self.tz).date()
        try:
            async with self.lock:
                table, team, cal = await self.load()
                task = table.find(task_id)
                if task is None:
                    return f"I couldn't find task `{task_id}` in the plan."
                if not task.is_done(self.settings.done_values):
                    return f"`{task.id}` isn't marked done any more, so there's nothing to undo."
                by = self.member_name(team, user)
                try:
                    await asyncio.to_thread(
                        self.store.reopen,
                        task.id,
                        task.title,
                        status,
                        signed_on,
                        by,
                        self.today(),
                        note,
                    )
                except UnsafeWriteError as exc:
                    return f"⚠️ I didn't change the Sheet: {exc}"
                await self._log(
                    cal, task, f"Sign-off undone in Discord (back to {status})", by, "Decision made"
                )
                self._cache = None
        except Exception:
            log.exception("Couldn't undo the sign-off of %s", task_id)
            self._cache = None
            return SHEET_BUSY
        await self.announce(
            f"↩️ **{user.display_name}** undid the sign-off of `{task.id}` {task.title}"
        )
        return f"↩️ `{task.id}` is back to **{status}**, and the sign-off is taken back."

    async def change_status(
        self, task_id: str, user: discord.abc.User, status: str, note: str = ""
    ) -> tuple[str, discord.ui.View | None]:
        if status.casefold() in self.settings.done_values:
            return await self.sign_off(task_id, user, note)
        change = await self.set_status(task_id, user, status, note)
        task = change.task
        if task is None:
            return change.error, None
        mark = STATUS_MARKS.get(status.casefold(), "▫️")
        if status.casefold() in ("blocked", "postponed", "cancelled"):
            extra = f"\n> {note}" if note else ""
            await self.announce(
                f"{mark} **{user.display_name}** set `{task.id}` {task.title} to {status}{extra}"
            )
        return f"{mark} `{task.id}` is now **{status}**.", None

    async def assign(self, task_id: str, member: discord.abc.User, by: discord.abc.User) -> str:
        async with self.lock:
            table, team, cal = await self.load()
            task = table.find(task_id)
            if task is None:
                return f"I couldn't find task `{task_id}` in the plan."
            denied = await self.allowed(task, team, by)
            if denied:
                return denied
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
            await self._log(
                cal,
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

        ch = await self.channel()
        summary = weekly_summary(plan, team, table.tasks, self.settings, cal, self.today())
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
                lines = [f"**{heading}**"]
                for t in items:
                    lines += [task_line(t), *task_details(t)]
                for text in chunks(lines):
                    await user.send(text)
                for view in done_views(items):
                    await user.send("Press a button when it's done:", view=view)
            except discord.HTTPException:
                failed.append(m.name)
        return failed


# -- slash commands --------------------------------------------------------------

HELP_TEXT = "\n".join(
    (
        "**📡 Dragonfly task bot**",
        "The bot runs our plan from the *Radar Detection Timeline* Sheet. Once a week it "
        "posts last week's progress and this week's focus, and DMs each of us our tasks. "
        "Midweek it DMs a reminder of what's still open, and it posts a heads-up a few "
        "days before each milestone.",
        "",
        "**Getting started**",
        "`/link` your name as it's written in the plan (once). Then your tasks come by DM.",
        "",
        "**Signing off**",
        "Press **Done** on a task in your DMs, or use `/done`. Add what you did and, if you "
        "have one, a link to the evidence (a doc, photo or file). It all goes into the "
        "Sheet's TASK BOARD and WORK LOG.",
        "Pressed it by mistake? Use **Undo** within 10 minutes.",
        "",
        "**Commands**",
        "`/tasks`: your open tasks (or someone else's)",
        "`/week`: everything in a week and who has it",
        "`/progress`: how much of each week is done",
        "`/status`: set a task to In progress, Blocked, Postponed…",
        "`/done`: sign off a task",
        "`/assign`: give a task to someone",
        "`/link`: connect your Discord account to your name",
        "`/plan`: post this week's plan now (admins)",
        "",
        "**Who can change what**",
        'You can sign off or change tasks you own, tasks owned by "All", and tasks with no '
        "owner yet. Admins can change anything. Only an admin can re-link a name.",
        "The bot never deletes or overwrites what's in the Sheet: it only fills in Status, "
        "dates, owners and notes, and adds WORK LOG rows.",
    )
)


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
        for t in now_:
            lines += [task_line(t), *task_details(t)]
        if not now_:
            lines.append("Nothing due yet.")
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
    @app_commands.describe(
        task="The task to sign off",
        note="What was done",
        link="A link to the evidence (a doc, photo or file), optional",
    )
    @app_commands.autocomplete(task=task_choices)
    async def done_cmd(interaction: discord.Interaction, task: str, note: str = "", link: str = ""):
        evidence = clean_link(link)
        if evidence is None:
            await interaction.response.send_message(BAD_LINK, ephemeral=True)
            return
        await interaction.response.defer(ephemeral=True, thinking=True)
        message, undo = await bot.sign_off(task, interaction.user, note.strip()[:300], evidence)
        await send_result(interaction, message, undo)

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
        message, undo = await bot.change_status(
            task, interaction.user, allowed[status.casefold()], note.strip()[:300]
        )
        await send_result(interaction, message, undo)

    @tree.command(name="assign", description="Give a task to someone")
    @app_commands.autocomplete(task=task_choices)
    async def assign_cmd(interaction: discord.Interaction, task: str, member: discord.Member):
        await interaction.response.defer(thinking=True)
        await interaction.followup.send(
            await bot.assign(task, member, interaction.user),
            allowed_mentions=discord.AllowedMentions.none(),
        )

    @tree.command(name="link", description="Connect your Discord account to your name in the plan")
    @app_commands.describe(
        name="Your name as it's written in the plan",
        member="Admins only: link someone else instead of yourself",
    )
    @app_commands.autocomplete(name=name_choices)
    async def link_cmd(
        interaction: discord.Interaction, name: str, member: discord.Member | None = None
    ):
        await interaction.response.defer(ephemeral=True)
        name = name.strip()[:60]
        target = member or interaction.user
        admin = await bot.is_admin(interaction.user)
        if target.id != interaction.user.id and not admin:
            await interaction.followup.send(
                "⛔ Only an admin can link someone else. Ask them to run `/link` themselves.",
                ephemeral=True,
            )
            return
        try:
            async with bot.lock:
                m = await asyncio.to_thread(bot.store.link_member, name, target.id, admin)
                bot._cache = None
        except UnsafeWriteError as exc:
            await interaction.followup.send(f"⛔ {exc}", ephemeral=True)
            return
        who_ = "you" if target.id == interaction.user.id else target.display_name
        await interaction.followup.send(
            f"Linked {who_} to **{m.name}**. Tasks for {m.name} now come by DM each week.",
            ephemeral=True,
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
        # The server can loosen who sees /plan, so check here too.
        if not await bot.is_admin(interaction.user):
            await interaction.followup.send("⛔ Only an admin can post the plan.", ephemeral=True)
            return
        plan = await bot.run_weekly(week)
        await interaction.followup.send(
            f"Posted week {plan.week}: {len(plan.open_tasks)} open tasks, "
            f"{len(plan.new_assignments)} newly assigned.",
            ephemeral=True,
        )

    @tree.command(name="help", description="What the bot does and how to use it")
    async def help_cmd(interaction: discord.Interaction):
        await interaction.response.send_message(HELP_TEXT, ephemeral=True)
