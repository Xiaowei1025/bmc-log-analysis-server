"""Conversation helpers that preserve history while allowing a fresh chat."""


def _group_clause(group_id):
    return ("group_id IS NULL", []) if group_id is None else ("group_id=?", [group_id])


def current_conversation(db, user_id: int, scope: str, requested_id: int | None = None, context_mode: str = "", group_id: int | None = None):
    conversation = None
    group_clause, group_params = _group_clause(group_id)
    if requested_id:
        conversation = db.execute(
            f"SELECT * FROM chat_conversations WHERE id=? AND user_id=? AND scope=? AND context_mode=? AND {group_clause}",
            (requested_id, user_id, scope, context_mode, *group_params),
        ).fetchone()
    if not conversation:
        conversation = db.execute(
            f"SELECT * FROM chat_conversations WHERE user_id=? AND scope=? AND context_mode=? AND {group_clause} ORDER BY updated_at DESC,id DESC LIMIT 1",
            (user_id, scope, context_mode, *group_params),
        ).fetchone()
    if not conversation:
        conversation_id = db.execute(
            "INSERT INTO chat_conversations (user_id,scope,context_mode,group_id,title) VALUES (?,?,?,?,?)",
            (user_id, scope, context_mode, group_id, "新对话"),
        ).lastrowid
        db.commit()
        conversation = db.execute("SELECT * FROM chat_conversations WHERE id=?", (conversation_id,)).fetchone()
    return conversation


def conversation_list(db, user_id: int, scope: str, context_mode: str = "", group_id: int | None = None):
    group_clause, group_params = _group_clause(group_id)
    return db.execute(
        f"SELECT * FROM chat_conversations WHERE user_id=? AND scope=? AND context_mode=? AND {group_clause} ORDER BY updated_at DESC,id DESC LIMIT 20",
        (user_id, scope, context_mode, *group_params),
    ).fetchall()


def create_conversation(db, user_id: int, scope: str, context_mode: str = "", group_id: int | None = None) -> int:
    conversation_id = db.execute(
        "INSERT INTO chat_conversations (user_id,scope,context_mode,group_id,title) VALUES (?,?,?,?,?)",
        (user_id, scope, context_mode, group_id, "新对话"),
    ).lastrowid
    db.commit()
    return conversation_id


def rename_conversation(
    db,
    user_id: int,
    conversation_id: int,
    scope: str,
    title: str,
    context_mode: str = "",
    group_id: int | None = None,
) -> str | None:
    """Rename one owned conversation within its context and optional group."""
    normalized = " ".join((title or "").split())[:60]
    if not normalized:
        raise ValueError("对话名称不能为空")
    group_clause, group_params = _group_clause(group_id)
    updated = db.execute(
        f"""UPDATE chat_conversations
           SET title=?,updated_at=CURRENT_TIMESTAMP
           WHERE id=? AND user_id=? AND scope=? AND context_mode=? AND {group_clause}""",
        (normalized, conversation_id, user_id, scope, context_mode, *group_params),
    )
    if updated.rowcount != 1:
        return None
    db.commit()
    return normalized


def touch_conversation(db, conversation_id: int, question: str):
    conversation = db.execute(
        "SELECT title FROM chat_conversations WHERE id=?",
        (conversation_id,),
    ).fetchone()
    title = (question.strip().replace("\n", " ")[:36] or "新对话") if conversation and conversation["title"] in {"新对话", "历史对话"} else None
    if title:
        db.execute(
            "UPDATE chat_conversations SET title=?,updated_at=CURRENT_TIMESTAMP WHERE id=?",
            (title, conversation_id),
        )
    else:
        db.execute(
            "UPDATE chat_conversations SET updated_at=CURRENT_TIMESTAMP WHERE id=?",
            (conversation_id,),
        )
