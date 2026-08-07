"""Group visibility helpers for the multi-user WeLink workspace.

The MVP keeps the existing ``created_by`` columns for backwards compatibility,
while new WeLink records can be assigned to a group.  A group membership is
the only way to share a source, recipient, run or issue with another user.
"""

from __future__ import annotations

from fastapi import HTTPException


def ensure_personal_group(db, user_id: int) -> int:
    """Return the user's private group, creating it and membership if needed."""
    row = db.execute(
        "SELECT id FROM welink_groups WHERE owner_id=? AND is_personal=1 ORDER BY id LIMIT 1",
        (user_id,),
    ).fetchone()
    if row:
        group_id = row["id"]
    else:
        group_id = db.execute(
            "INSERT INTO welink_groups (name,description,owner_id,is_personal) VALUES (?,?,?,1)",
            ("个人空间", "仅自己可见的 WeLink 巡检配置。", user_id),
        ).lastrowid
    db.execute(
        "INSERT OR IGNORE INTO welink_group_members (group_id,user_id,member_role,added_by) VALUES (?,?,?,?)",
        (group_id, user_id, "owner", user_id),
    )
    return group_id


def visible_group_ids(db, user) -> list[int]:
    """Return groups visible to a user; global admins can audit every group."""
    if user["role"] == "admin":
        return [row["id"] for row in db.execute("SELECT id FROM welink_groups ORDER BY id").fetchall()]
    ensure_personal_group(db, user["id"])
    return [
        row["group_id"]
        for row in db.execute(
            "SELECT group_id FROM welink_group_members WHERE user_id=? ORDER BY group_id",
            (user["id"],),
        ).fetchall()
    ]


def group_rows(db, user) -> list[dict]:
    """Return visible groups with the current user's membership role."""
    ensure_personal_group(db, user["id"])
    if user["role"] == "admin":
        rows = db.execute(
            """SELECT g.*, COALESCE(m.member_role,'admin') AS current_role,
                      (SELECT COUNT(*) FROM welink_group_members x WHERE x.group_id=g.id) AS member_count
               FROM welink_groups g LEFT JOIN welink_group_members m
                 ON m.group_id=g.id AND m.user_id=? ORDER BY g.is_personal, g.name""",
            (user["id"],),
        ).fetchall()
    else:
        rows = db.execute(
            """SELECT g.*, m.member_role AS current_role,
                      (SELECT COUNT(*) FROM welink_group_members x WHERE x.group_id=g.id) AS member_count
               FROM welink_groups g JOIN welink_group_members m ON m.group_id=g.id
              WHERE m.user_id=? ORDER BY g.is_personal, g.name""",
            (user["id"],),
        ).fetchall()
    return [dict(row) for row in rows]


def resolve_group(db, user, group_id: int | None = None) -> dict:
    """Resolve a selected group and reject cross-group writes."""
    # A read or validation of an explicitly supplied group must not create a
    # personal-group row first.  Apart from unnecessary writes, doing so can
    # leave an open SQLite transaction when an invalid group raises 404 and
    # make the next browser request report ``database is locked``.  Only the
    # implicit/default workspace needs lazy personal-group creation.
    target_id = int(group_id) if group_id else ensure_personal_group(db, user["id"])
    row = db.execute("SELECT * FROM welink_groups WHERE id=?", (target_id,)).fetchone()
    if not row:
        raise HTTPException(404, "巡检分组不存在")
    if user["role"] == "admin":
        return dict(row)
    membership = db.execute(
        "SELECT member_role FROM welink_group_members WHERE group_id=? AND user_id=?",
        (target_id, user["id"]),
    ).fetchone()
    if not membership:
        raise HTTPException(403, "你不在这个巡检分组中")
    return dict(row)


def can_manage_group(db, user, group_id: int | None) -> bool:
    if user["role"] == "admin":
        return True
    row = db.execute(
        "SELECT member_role FROM welink_group_members WHERE group_id=? AND user_id=?",
        (group_id, user["id"]),
    ).fetchone()
    return bool(row and row["member_role"] == "owner")


def assert_group_manager(db, user, group_id: int | None):
    if not can_manage_group(db, user, group_id):
        raise HTTPException(403, "只有巡检分组负责人或平台管理员可以修改共享配置")


def scoped_in_clause(column: str, group_ids: list[int]) -> tuple[str, list[int]]:
    """Build a safe SQL fragment for group visibility checks."""
    if not group_ids:
        return "1=0", []
    placeholders = ",".join("?" for _ in group_ids)
    return f"{column} IN ({placeholders})", list(group_ids)
