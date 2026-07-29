"""Persistent non-secret runtime switches shared by platform modules."""


def get_setting(db, key: str, default: str = "") -> str:
    row = db.execute("SELECT value FROM app_settings WHERE key=?", (key,)).fetchone()
    return row["value"] if row else default


def set_setting(db, key: str, value: str, user_id: int) -> None:
    db.execute(
        """INSERT INTO app_settings (key,value,updated_by,updated_at) VALUES (?,?,?,CURRENT_TIMESTAMP)
        ON CONFLICT(key) DO UPDATE SET value=excluded.value,updated_by=excluded.updated_by,updated_at=CURRENT_TIMESTAMP""",
        (key, value, user_id),
    )
