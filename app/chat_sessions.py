"""Conversation helpers that preserve history while allowing a fresh chat."""


def current_conversation(db, user_id: int, scope: str, requested_id: int | None = None, context_mode: str = ""):
    conversation = None
    if requested_id:
        conversation = db.execute(
            "SELECT * FROM chat_conversations WHERE id=? AND user_id=? AND scope=? AND context_mode=?",
            (requested_id, user_id, scope, context_mode),
        ).fetchone()
    if not conversation:
        conversation = db.execute(
            "SELECT * FROM chat_conversations WHERE user_id=? AND scope=? AND context_mode=? ORDER BY updated_at DESC,id DESC LIMIT 1",
            (user_id, scope, context_mode),
        ).fetchone()
    if not conversation:
        conversation_id = db.execute(
            "INSERT INTO chat_conversations (user_id,scope,context_mode,title) VALUES (?,?,?,?)",
            (user_id, scope, context_mode, "新对话"),
        ).lastrowid
        db.commit()
        conversation = db.execute("SELECT * FROM chat_conversations WHERE id=?", (conversation_id,)).fetchone()
    return conversation


def conversation_list(db, user_id: int, scope: str, context_mode: str = ""):
    return db.execute(
        "SELECT * FROM chat_conversations WHERE user_id=? AND scope=? AND context_mode=? ORDER BY updated_at DESC,id DESC LIMIT 20",
        (user_id, scope, context_mode),
    ).fetchall()


def create_conversation(db, user_id: int, scope: str, context_mode: str = "") -> int:
    conversation_id = db.execute(
        "INSERT INTO chat_conversations (user_id,scope,context_mode,title) VALUES (?,?,?,?)",
        (user_id, scope, context_mode, "新对话"),
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
) -> str | None:
    """Rename one owned conversation without exposing another user's record."""
    normalized = " ".join((title or "").split())[:60]
    if not normalized:
        raise ValueError("对话名称不能为空")
    updated = db.execute(
        """UPDATE chat_conversations
           SET title=?,updated_at=CURRENT_TIMESTAMP
           WHERE id=? AND user_id=? AND scope=? AND context_mode=?""",
        (normalized, conversation_id, user_id, scope, context_mode),
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
