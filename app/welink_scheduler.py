"""One-shot scheduler entry point for the WeLink inspection MVP.

The web process only stores schedules.  A systemd timer invokes this module
once per minute, so multiple Uvicorn workers cannot accidentally run the same
inspection.  It only creates a connector job; the user's Windows connector
performs the actual WeLink CLI work.
"""

from __future__ import annotations

import json
from datetime import datetime

from .database import connection
from .runtime_settings import get_setting
from .welink_module import _enqueue_connector_job


def claim_due_schedules(now: datetime | None = None) -> list[int]:
    now = now or datetime.now()
    current_time = now.strftime("%H:%M")
    stamp = now.strftime("%Y-%m-%d %H:%M")
    db = connection()
    created: list[int] = []
    try:
        if get_setting(db, "welink_run_mode", "demo") != "production":
            return created
        rows = db.execute(
            "SELECT s.group_id,g.owner_id FROM welink_schedules s JOIN welink_groups g ON g.id=s.group_id WHERE s.enabled=1 AND s.schedule_time=?",
            (current_time,),
        ).fetchall()
        for row in rows:
            group_id, owner_id = row["group_id"], row["owner_id"]
            key = f"schedule:{group_id}:{stamp}"
            if db.execute("SELECT 1 FROM welink_jobs WHERE idempotency_key=?", (key,)).fetchone():
                continue
            if db.execute("SELECT 1 FROM welink_runs WHERE group_id=? AND run_mode='production' AND status IN ('queued','awaiting_bridge') LIMIT 1", (group_id,)).fetchone():
                continue
            sources = db.execute("SELECT id,source_type,display_name,conversation_key,note,lookback_days FROM welink_sources WHERE group_id=? AND enabled=1", (group_id,)).fetchall()
            recipients = db.execute("SELECT id,recipient_type,display_name,receiver_key FROM welink_recipients WHERE group_id=? AND enabled=1", (group_id,)).fetchall()
            if not sources:
                continue
            summary = "定时巡检已创建，等待 Windows 本地连接器领取。"
            run_id = db.execute(
                "INSERT INTO welink_runs (status,source_count,recipient_count,summary,run_mode,progress,current_stage,requested_by,group_id) VALUES ('queued',?,?,?,?,?,?,?,?)",
                (len(sources), len(recipients), summary, "production", 10, "等待本地连接器领取", owner_id, group_id),
            ).lastrowid
            _enqueue_connector_job(db, {"id": owner_id}, group_id, sources, recipients, run_id=run_id, idempotency_key=key)
            created.append(run_id)
        db.commit()
        return created
    finally:
        db.close()


if __name__ == "__main__":
    run_ids = claim_due_schedules()
    print(json.dumps({"created_run_ids": run_ids}, ensure_ascii=False))
