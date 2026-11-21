"""Who may change what. Pure, so the rules can be tested without Discord.

Admins (Manage Server, or the role in TASKBOT_ADMIN_ROLE) may do anything; the bot
checks that separately, and only when these rules say no.
"""

from __future__ import annotations

from .sheet import Member, Task, is_everyone, people_for


def linked(team: list[Member], discord_id: int) -> Member | None:
    return next((m for m in team if m.discord_id == discord_id), None)


def may_change(task: Task, team: list[Member], discord_id: int) -> tuple[bool, str]:
    """Whether this Discord user may sign off or change the status of ``task``.

    Allowed: one of the task's owners, anyone when it's owned by "All", and any linked
    member when it has no owner yet. Returns (allowed, reason when not).
    """
    me = linked(team, discord_id)
    if me is None:
        return False, "Link your Discord account to your name in the plan first with `/link`."
    if not task.assignees or any(is_everyone(n) for n in task.assignees):
        return True, ""
    if me in people_for(task.assignees, team):
        return True, ""
    owners = " + ".join(task.assignees)
    return False, f"`{task.id}` belongs to {owners}. Only its owners or an admin can change it."
