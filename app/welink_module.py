"""Safe configuration and audit boundary for the WeLink inspection module."""

import json
import hashlib
import os
import secrets
import urllib.error
import urllib.request
from datetime import datetime, timezone

from fastapi import Form, HTTPException, Request
from fastapi.responses import HTMLResponse, JSONResponse, StreamingResponse

from .chat_sessions import conversation_list, create_conversation, current_conversation, rename_conversation, touch_conversation
from .database import connection
from .runtime_settings import get_setting, set_setting
from .welink_groups import (
    assert_group_manager,
    can_manage_group,
    ensure_personal_group,
    group_rows,
    resolve_group,
    scoped_in_clause,
    visible_group_ids,
)

SOURCE_TYPES = {"notice_group": "问题通报群", "discussion_group": "问题讨论群", "person": "个人消息"}
RECIPIENT_TYPES = {"group": "群组", "person": "个人"}
REASONING_START = "[[BMC_REASONING_START]]"
REASONING_END = "[[BMC_REASONING_END]]"
NOTICE_MESSAGES = {
    "mode_demo": "已切换到演示模式。只使用本地模拟数据，不读取或发送 WeLink 消息。",
    "mode_production": "已切换到生产模式。只有桥接和消息源就绪后才能开始真实巡检。",
    "source_created": "消息源已添加。",
    "source_updated": "消息源配置已更新。",
    "source_deleted": "消息源已删除。",
    "sources_deleted": "已删除选中的消息源。",
    "source_toggled": "消息源启停状态已更新。",
    "sources_enabled": "当前账号的消息源已全部启用。",
    "sources_disabled": "当前账号的消息源已全部暂停。",
    "sources_discussion": "当前只启用了问题讨论群。",
    "recipient_created": "报告接收方已添加。",
    "recipient_updated": "报告接收方配置已更新。",
    "recipient_deleted": "报告接收方已删除。",
    "recipient_toggled": "报告接收方启停状态已更新。",
    "run_completed": "巡检已完成，结果已写入审计台账。",
    "run_queued": "巡检任务已提交到内网桥接，可在审计台账查看状态。",
    "report_generated": "当前运行模式的巡检报告已生成。",
    "issue_updated": "问题状态已更新。",
    "action_updated": "行动项状态已更新。",
    "schedule_saved": "自动巡检规则已保存。",
    "group_created": "巡检分组已创建。",
    "group_updated": "巡检分组已更新。",
    "group_deleted": "巡检分组已删除。",
    "member_added": "分组成员已添加。",
    "connector_revoked": "连接器已撤销。",
    "conversation_renamed": "对话名称已更新。",
}
ERROR_MESSAGES = {
    "source": "消息源未保存，请检查类型、名称和群标识或工号。",
    "recipient": "接收方未保存，请检查类型、名称和群标识或工号。",
    "duplicate": "存在相同类型和标识的配置，请直接编辑原配置。",
    "no_sources": "生产巡检至少需要一个已启用的消息源。",
    "bridge": "生产巡检尚不可用：请先在服务器配置内网桥接地址和令牌。",
    "run_active": "已有生产巡检正在排队或等待桥接，请勿重复提交。",
    "source_selection": "请至少选择一个消息源。",
}


def _welink_redirect(notice: str | None = None, error: str | None = None, group_id: int | None = None, anchor: str | None = None, settings: bool = False) -> str:
    """Build a stable WeLink return URL without losing the active workspace."""
    query = []
    if group_id not in (None, ""):
        query.append(f"group_id={int(group_id)}")
    if notice:
        query.append(f"notice={notice}")
    if error:
        query.append(f"error={error}")
    if settings:
        query.append("settings=1")
    location = "/welink" + ("?" + "&".join(query) if query else "")
    return location + (f"#{anchor}" if anchor else "")


def _seed_demo_issues(db):
    """Visible demo data only; production facts must come from the bridge."""
    if db.execute("SELECT 1 FROM welink_issues WHERE is_demo=1 LIMIT 1").fetchone():
        return
    samples = [
        ("Atlas 900 节点 GPU 温度告警", "P1", "处理中", "训练任务存在降频与中断风险", "张工", "今天 16:00", "A03 机柜 4 台节点出现 GPU 过温告警。", "已下线训练任务，备件申请完成，等待更换验证。", "散热模组转速波动，仍待替换验证。", "同机柜存在多台过温，风险尚未解除。", "更换异常风扇，复测 30 分钟温度曲线并回填结论。", ["张工", "王工", "陈工"]),
        ("KunLun 主板 RMA 备件到货延期", "P2", "待协调", "2 台业务备用机恢复计划延后", "李工", "今天 14:00", "主板 RMA 备件交期未确认。", "供应商尚未给出明确到货日期。", "供应链交期未锁定。", "超过承诺窗口将影响备用资源池。", "确认到货时间；无法满足时申请同型号调拨。", ["李工", "供应链"]),
        ("A03 机柜进风温度波动", "P2", "待观察", "暂未影响业务，存在关联散热风险", "王工", "明天 11:00", "机柜进风温度短时波动。", "正在补采集温湿度记录。", "尚未确认是否为环境侧诱因。", "与 GPU 告警时间段重叠。", "核验 BMS 温湿度告警并交叉确认。", ["王工", "陈工"]),
    ]
    for index, item in enumerate(samples):
        issue_id = db.execute("""INSERT INTO welink_issues (title,severity,status,impact,owner,due_at,background,latest_progress,root_cause,risk_reason,next_step,participants,is_demo)
            VALUES (?,?,?,?,?,?,?,?,?,?,?,?,1)""", (*item[:-1], json.dumps(item[-1], ensure_ascii=False))).lastrowid
        evidence = [("Atlas 900 故障讨论", "张工", "今天 09:12", "节点 GPU 温度连续 10 分钟超过阈值，已先下线训练任务。", 1)] if index == 0 else [("问题讨论群", item[4], "今天 09:40", item[7], 1)]
        for row in evidence:
            db.execute("INSERT INTO welink_issue_evidence (issue_id,source_name,author,message_time,excerpt,is_key) VALUES (?,?,?,?,?,?)", (issue_id, *row))
        db.execute("INSERT INTO welink_issue_actions (issue_id,title,owner,due_at,status,priority) VALUES (?,?,?,?,?,?)", (issue_id, item[10], item[4], item[5], "进行中" if index == 0 else "待执行", "紧急" if index == 0 else "高"))


def _issue_context(db, include_demo=True, group_ids=None):
    conditions, params = [], []
    if not include_demo:
        conditions.append("is_demo=0")
    if group_ids is not None:
        group_clause, group_params = scoped_in_clause("group_id", group_ids)
        # Demo cards are intentionally global. Production rows must have a
        # concrete group (or the creating user fallback for pre-migration rows)
        # and must never become visible merely because group_id is NULL.
        conditions.append(f"(is_demo=1 OR {group_clause})")
        params.extend(group_params)
    sql = "SELECT * FROM welink_issues"
    if conditions:
        sql += " WHERE " + " AND ".join(conditions)
    issues = db.execute(sql + " ORDER BY CASE severity WHEN 'P1' THEN 1 WHEN 'P2' THEN 2 ELSE 3 END, updated_at DESC", params).fetchall()
    result = []
    for issue in issues:
        item = dict(issue)
        item["participants"] = json.loads(item["participants"] or "[]")
        item["evidence"] = db.execute("SELECT * FROM welink_issue_evidence WHERE issue_id=? ORDER BY id", (issue["id"],)).fetchall()
        item["actions"] = db.execute("SELECT * FROM welink_issue_actions WHERE issue_id=? ORDER BY id", (issue["id"],)).fetchall()
        result.append(item)
    return result


def _clean(value: str, limit: int) -> str:
    return (value or "").strip()[:limit]


def _manage(user, item, db=None):
    if not item:
        raise HTTPException(404, "配置不存在")
    if user["role"] == "admin" or item["created_by"] == user["id"]:
        return
    if db is not None and item.keys() and "group_id" in item.keys() and can_manage_group(db, user, item["group_id"]):
        return
    if item["created_by"] != user["id"]:
        raise HTTPException(403, "只能管理自己创建的配置")


def _can_manage(user, item, db) -> bool:
    """Mirror the server-side config permission in the page rendering."""
    if not item:
        return False
    if user["role"] == "admin" or item["created_by"] == user["id"]:
        return True
    return bool(item["group_id"] and can_manage_group(db, user, item["group_id"]))


def _mode(db) -> str:
    return get_setting(db, "welink_run_mode", os.getenv("WELINK_DEFAULT_MODE", "demo").strip() or "demo")


def _group_id_from_form(db, user, group_id: int | str | None = None) -> int:
    """Resolve and validate a target group for every write operation."""
    if not isinstance(group_id, (int, str, type(None))):
        group_id = getattr(group_id, "default", None)
    try:
        value = int(group_id) if group_id not in (None, "") else None
    except (TypeError, ValueError):
        raise HTTPException(400, "巡检分组无效")
    return resolve_group(db, user, value)["id"]


def _connector_token_hash(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def _connector_device(db, request: Request):
    header = request.headers.get("authorization", "")
    if not header.lower().startswith("bearer "):
        raise HTTPException(401, "连接器需要 Bearer 令牌")
    token = header.split(" ", 1)[1].strip()
    if not token:
        raise HTTPException(401, "连接器令牌为空")
    device = db.execute(
        "SELECT * FROM welink_connector_devices WHERE token_hash=? AND status='active'",
        (_connector_token_hash(token),),
    ).fetchone()
    if not device:
        raise HTTPException(401, "连接器令牌无效或已撤销")
    db.execute("UPDATE welink_connector_devices SET last_seen_at=CURRENT_TIMESTAMP WHERE id=?", (device["id"],))
    return device


def _enqueue_connector_job(db, user, group_id: int, sources, recipients, run_id: int | None = None, idempotency_key: str | None = None):
    key = idempotency_key or secrets.token_urlsafe(24)
    payload = {
        "sources": [dict(item) for item in sources],
        "recipients": [dict(item) for item in recipients],
        "requested_at": datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z"),
    }
    try:
        job_id = db.execute(
            "INSERT INTO welink_jobs (group_id,requested_by,run_id,payload,idempotency_key) VALUES (?,?,?,?,?)",
            (group_id, user["id"], run_id, json.dumps(payload, ensure_ascii=False), key),
        ).lastrowid
    except Exception:
        row = db.execute("SELECT id FROM welink_jobs WHERE idempotency_key=?", (key,)).fetchone()
        if not row:
            raise
        job_id = row["id"]
    return job_id, key


def _ingest_connector_result(db, job, data):
    """Persist only the connector's structured, bounded result fields."""
    issues = data.get("issues", []) if isinstance(data.get("issues", []), list) else []
    for raw in issues[:200]:
        if not isinstance(raw, dict) or not _clean(str(raw.get("title", "")), 240):
            continue
        title = _clean(str(raw.get("title")), 240)
        existing = db.execute("SELECT id FROM welink_issues WHERE run_id=? AND group_id=? AND title=?", (job["run_id"], job["group_id"], title)).fetchone()
        values = (
            title, _clean(str(raw.get("severity", "P2")), 8), _clean(str(raw.get("status", "处理中")), 20),
            _clean(str(raw.get("impact", "")), 500), _clean(str(raw.get("owner", "")), 120), _clean(str(raw.get("due_at", "")), 80),
            _clean(str(raw.get("background", "")), 2000), _clean(str(raw.get("latest_progress", "")), 2000), _clean(str(raw.get("root_cause", "")), 2000),
            _clean(str(raw.get("risk_reason", "")), 2000), _clean(str(raw.get("next_step", "")), 2000), json.dumps(raw.get("participants", []) if isinstance(raw.get("participants", []), list) else [], ensure_ascii=False)[:4000],
        )
        if existing:
            issue_id = existing["id"]
            db.execute("""UPDATE welink_issues SET severity=?,status=?,impact=?,owner=?,due_at=?,background=?,latest_progress=?,root_cause=?,risk_reason=?,next_step=?,participants=?,updated_at=CURRENT_TIMESTAMP WHERE id=?""", (*values[1:], issue_id))
        else:
            issue_id = db.execute("""INSERT INTO welink_issues (title,severity,status,impact,owner,due_at,background,latest_progress,root_cause,risk_reason,next_step,participants,run_id,group_id,created_by,is_demo) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,0)""", (*values, job["run_id"], job["group_id"], job["requested_by"])).lastrowid
        for evidence in (raw.get("evidence", []) if isinstance(raw.get("evidence", []), list) else [])[:50]:
            if isinstance(evidence, dict) and _clean(str(evidence.get("excerpt", "")), 2000):
                db.execute("INSERT INTO welink_issue_evidence (issue_id,source_name,author,message_time,excerpt,is_key) VALUES (?,?,?,?,?,?)", (issue_id, _clean(str(evidence.get("source_name", "WeLink")), 160), _clean(str(evidence.get("author", "")), 120), _clean(str(evidence.get("message_time", "")), 80), _clean(str(evidence.get("excerpt")), 2000), 1 if evidence.get("is_key") else 0))
        for action in (raw.get("actions", []) if isinstance(raw.get("actions", []), list) else [])[:50]:
            if isinstance(action, dict) and _clean(str(action.get("title", "")), 300):
                db.execute("INSERT INTO welink_issue_actions (issue_id,title,owner,due_at,status,priority) VALUES (?,?,?,?,?,?)", (issue_id, _clean(str(action.get("title")), 300), _clean(str(action.get("owner", "")), 120), _clean(str(action.get("due_at", "")), 80), _clean(str(action.get("status", "待执行")), 20), _clean(str(action.get("priority", "高")), 20)))
    report = _clean(str(data.get("report", "")), 500000)
    if report and job["run_id"]:
        db.execute("INSERT INTO welink_reports (run_id,run_mode,content,created_by,group_id) VALUES (?,?,?,?,?)", (job["run_id"], "production", report, job["requested_by"], job["group_id"]))


def _bridge_run(sources, recipients, group_id=None):
    """Call the fixed in-network bridge contract; never invoke a shell command."""
    base_url = os.getenv("WELINK_AGENT_BRIDGE_URL", "").strip().rstrip("/")
    token = os.getenv("WELINK_AGENT_BRIDGE_TOKEN", "").strip()
    if not base_url or not token:
        return "awaiting_bridge", "生产模式尚未配置内网桥接地址或服务令牌，未读取或发送任何消息。"
    payload = {
        "sources": [dict(item) for item in sources],
        "recipients": [dict(item) for item in recipients],
        "group_id": group_id,
        "requested_at": "platform",
    }
    request = urllib.request.Request(
        base_url + "/v1/welink/runs",
        data=json.dumps(payload, ensure_ascii=False).encode("utf-8"),
        headers={"Authorization": "Bearer " + token, "Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(request, timeout=20) as response:
            body = json.loads(response.read().decode("utf-8", errors="replace") or "{}")
        status = str(body.get("status", "queued"))
        if status not in {"queued", "completed", "failed"}:
            status = "queued"
        return status, str(body.get("summary") or "巡检任务已交给内网桥接服务执行。")[:1000]
    except (urllib.error.URLError, TimeoutError, ValueError) as error:
        return "failed", f"内网桥接服务调用失败：{error}"


def register_welink_routes(app, page, require_user, redirect, llm_provider=None):
    @app.get("/welink", response_class=HTMLResponse)
    def welink_dashboard(request: Request, chat: int = 0, group_id: int = 0):
        user = require_user(request)
        db = connection()
        mode = _mode(db)
        selected_group_id = _group_id_from_form(db, user, group_id or None)
        groups = group_rows(db, user)
        group_ids = [selected_group_id]
        sources = db.execute(
            "SELECT s.*,u.username FROM welink_sources s JOIN users u ON u.id=s.created_by WHERE (s.group_id=? OR (s.group_id IS NULL AND s.created_by=?)) ORDER BY s.enabled DESC,s.updated_at DESC",
            [selected_group_id, user["id"]],
        ).fetchall()
        recipients = db.execute(
            "SELECT r.*,u.username FROM welink_recipients r JOIN users u ON u.id=r.created_by WHERE (r.group_id=? OR (r.group_id IS NULL AND r.created_by=?)) ORDER BY r.enabled DESC,r.created_at DESC",
            [selected_group_id, user["id"]],
        ).fetchall()
        runs = db.execute(
            "SELECT r.*,u.username FROM welink_runs r JOIN users u ON u.id=r.requested_by WHERE (r.group_id=? OR (r.group_id IS NULL AND r.requested_by=?)) ORDER BY r.created_at DESC LIMIT 8",
            [selected_group_id, user["id"]],
        ).fetchall()
        active_run = next((item for item in runs if item["run_mode"] == mode and item["status"] in {"queued", "awaiting_bridge"}), None)
        if mode == "demo": _seed_demo_issues(db); db.commit()
        issues = _issue_context(db, include_demo=mode == "demo", group_ids=group_ids)
        active_issue_count = sum(1 for item in issues if item["status"] != "已闭环")
        critical_issue_count = sum(1 for item in issues if item["severity"] == "P1" and item["status"] != "已闭环")
        pending_action_count = sum(1 for item in issues for action in item["actions"] if action["status"] != "已完成")
        report = db.execute(
            "SELECT * FROM welink_reports WHERE (group_id=? OR (group_id IS NULL AND created_by=?)) AND run_mode=? ORDER BY id DESC LIMIT 1",
            [selected_group_id, user["id"], mode],
        ).fetchone()
        active_conversation = current_conversation(db, user["id"], "welink", chat or None, mode, selected_group_id)
        chat_history = db.execute(
            "SELECT role,content,created_at FROM welink_chat_messages WHERE user_id=? AND conversation_id=? ORDER BY id ASC LIMIT 100",
            (user["id"], active_conversation["id"]),
        ).fetchall()
        conversations = conversation_list(db, user["id"], "welink", mode, selected_group_id)
        schedule = db.execute("SELECT enabled,schedule_time FROM welink_schedules WHERE group_id=?", (selected_group_id,)).fetchone()
        if schedule is None:
            schedule_enabled = get_setting(db, "welink_schedule_enabled", "0") == "1"
            schedule_time = get_setting(db, "welink_schedule_time", "08:00")
        else:
            schedule_enabled, schedule_time = bool(schedule["enabled"]), schedule["schedule_time"]
        bridge_configured = bool(os.getenv("WELINK_AGENT_BRIDGE_URL", "").strip() and os.getenv("WELINK_AGENT_BRIDGE_TOKEN", "").strip())
        devices = db.execute("SELECT id,device_name,status,last_seen_at,created_at FROM welink_connector_devices WHERE user_id=? ORDER BY id DESC", (user["id"],)).fetchall()
        managed_source_ids = [item["id"] for item in sources if _can_manage(user, item, db)]
        managed_recipient_ids = [item["id"] for item in recipients if _can_manage(user, item, db)]
        can_manage_group_configs = can_manage_group(db, user, selected_group_id)
        notice_message = NOTICE_MESSAGES.get(request.query_params.get("notice", ""))
        error_message = ERROR_MESSAGES.get(request.query_params.get("error", ""))
        db.close()
        return page(request, "welink.html", sources=sources, recipients=recipients, runs=runs, active_run=active_run, issues=issues, active_issue_count=active_issue_count, critical_issue_count=critical_issue_count, pending_action_count=pending_action_count, latest_report=report, chat_history=chat_history, conversations=conversations, active_conversation=active_conversation, groups=groups, selected_group_id=selected_group_id, user_role=user["role"], devices=devices, managed_source_ids=managed_source_ids, managed_recipient_ids=managed_recipient_ids, can_manage_group_configs=can_manage_group_configs, settings_open=request.query_params.get("settings") == "1", schedule_enabled=schedule_enabled, schedule_time=schedule_time, source_types=SOURCE_TYPES, recipient_types=RECIPIENT_TYPES, bridge_configured=bridge_configured, connector_enabled=os.getenv("WELINK_CONNECTOR_ENABLED", "0").strip().lower() in {"1", "true", "yes"}, production_ready=(bridge_configured or os.getenv("WELINK_CONNECTOR_ENABLED", "0").strip().lower() in {"1", "true", "yes"}) and any(item["enabled"] for item in sources), run_mode=mode, notice_message=notice_message, error_message=error_message, can_switch_mode=user["role"] == "admin" or os.getenv("APP_ENV", "development").strip().lower() != "production")

    @app.post("/welink/mode")
    def change_mode(request: Request, run_mode: str = Form()):
        user = require_user(request)
        if user["role"] != "admin" and os.getenv("APP_ENV", "development").strip().lower() == "production":
            raise HTTPException(403, "只有管理员可以切换运行模式")
        if run_mode not in {"demo", "production"}:
            raise HTTPException(400, "运行模式无效")
        db = connection(); set_setting(db, "welink_run_mode", run_mode, user["id"]); db.commit(); db.close()
        return redirect(_welink_redirect(notice=f"mode_{run_mode}"))

    @app.post("/welink/groups")
    def create_group(request: Request, name: str = Form(), description: str = Form("")):
        user = require_user(request)
        name, description = _clean(name, 80), _clean(description, 300)
        if not name:
            raise HTTPException(400, "分组名称不能为空")
        db = connection()
        try:
            group_id = db.execute(
                "INSERT INTO welink_groups (name,description,owner_id,is_personal) VALUES (?,?,?,0)",
                (name, description, user["id"]),
            ).lastrowid
            db.execute(
                "INSERT INTO welink_group_members (group_id,user_id,member_role,added_by) VALUES (?,?,?,?)",
                (group_id, user["id"], "owner", user["id"]),
            )
            db.commit()
        except Exception:
            db.rollback(); db.close()
            raise HTTPException(409, "你已经创建过同名巡检分组")
        db.close()
        return redirect(_welink_redirect(notice="group_created", group_id=group_id, anchor="group-settings", settings=True))

    @app.post("/welink/groups/{group_id}/edit")
    def edit_group(request: Request, group_id: int, name: str = Form(), description: str = Form("")):
        user = require_user(request); db = connection()
        group = resolve_group(db, user, group_id); assert_group_manager(db, user, group_id)
        if group["is_personal"]:
            db.close(); raise HTTPException(400, "个人空间不能改名")
        name = _clean(name, 80)
        if not name:
            db.close(); raise HTTPException(400, "分组名称不能为空")
        try:
            db.execute("UPDATE welink_groups SET name=?,description=?,updated_at=CURRENT_TIMESTAMP WHERE id=?", (name, _clean(description, 300), group_id)); db.commit()
        except Exception:
            db.rollback(); db.close(); raise HTTPException(409, "分组名称已存在")
        db.close(); return redirect(_welink_redirect(notice="group_updated", group_id=group_id, anchor="group-settings", settings=True))

    @app.post("/welink/groups/{group_id}/delete")
    def delete_group(request: Request, group_id: int):
        user = require_user(request); db = connection()
        group = resolve_group(db, user, group_id); assert_group_manager(db, user, group_id)
        if group["is_personal"]:
            db.close(); raise HTTPException(400, "个人空间不能删除")
        db.execute("DELETE FROM welink_groups WHERE id=?", (group_id,)); db.commit(); db.close()
        return redirect(_welink_redirect(notice="group_deleted", anchor="group-settings", settings=True))

    @app.post("/welink/groups/{group_id}/members")
    def add_group_member(request: Request, group_id: int, username: str = Form(), member_role: str = Form("member")):
        user = require_user(request); db = connection(); resolve_group(db, user, group_id); assert_group_manager(db, user, group_id)
        target = db.execute("SELECT id FROM users WHERE username=?", (_clean(username, 120),)).fetchone()
        if not target:
            db.close(); raise HTTPException(404, "找不到该本地账号；IDaaS 接入后请使用已同步账号")
        if member_role not in {"member", "owner"}:
            db.close(); raise HTTPException(400, "成员角色无效")
        db.execute("INSERT INTO welink_group_members (group_id,user_id,member_role,added_by) VALUES (?,?,?,?) ON CONFLICT(group_id,user_id) DO UPDATE SET member_role=excluded.member_role", (group_id, target["id"], member_role, user["id"])); db.commit(); db.close()
        return redirect(_welink_redirect(notice="member_added", group_id=group_id, anchor="group-settings", settings=True))

    @app.post("/welink/groups/{group_id}/members/{member_id}/delete")
    def remove_group_member(request: Request, group_id: int, member_id: int):
        user = require_user(request); db = connection(); group = resolve_group(db, user, group_id); assert_group_manager(db, user, group_id)
        if member_id == group["owner_id"]:
            db.close(); raise HTTPException(400, "不能移除分组负责人")
        db.execute("DELETE FROM welink_group_members WHERE group_id=? AND user_id=?", (group_id, member_id)); db.commit(); db.close()
        return redirect(_welink_redirect(group_id=group_id, anchor="group-settings", settings=True))

    @app.post("/welink/sources")
    def create_source(request: Request, source_type: str = Form(), display_name: str = Form(), conversation_key: str = Form(), note: str = Form(""), lookback_days: int = Form(3), group_id: int = Form(0)):
        user = require_user(request)
        source_type, display_name, conversation_key = _clean(source_type, 32), _clean(display_name, 120), _clean(conversation_key, 160)
        if source_type not in SOURCE_TYPES or not display_name or not conversation_key:
            return redirect(_welink_redirect(error="source", group_id=group_id or None, anchor="sources"))
        days = max(0, min(int(lookback_days or 0), 365))
        if source_type != "discussion_group" and days == 0:
            days = 3
        db = connection()
        target_group = _group_id_from_form(db, user, group_id or None)
        try:
            db.execute("INSERT INTO welink_sources (source_type,display_name,conversation_key,note,lookback_days,created_by,group_id) VALUES (?,?,?,?,?,?,?)", (source_type, display_name, conversation_key, _clean(note, 500), days, user["id"], target_group))
            db.commit()
        except Exception:
            db.rollback()
            return redirect(_welink_redirect(error="duplicate", group_id=target_group, anchor="sources"))
        finally:
            db.close()
        return redirect(_welink_redirect(notice="source_created", group_id=target_group, anchor="sources"))

    @app.post("/welink/sources/bulk/{action}")
    def bulk_sources(request: Request, action: str, source_ids: str = Form(""), group_id: int = 0):
        """Apply one explicit bulk operation to the current user's sources.

        This route must be registered before ``/welink/sources/{source_id}/{action}``:
        otherwise FastAPI attempts to parse the literal ``bulk`` segment as an int
        and returns a misleading 422 response.
        """
        user = require_user(request); db = connection(); target_group = _group_id_from_form(db, user, group_id or request.query_params.get("group_id") or None); assert_group_manager(db, user, target_group)
        if action == "enable":
            db.execute("UPDATE welink_sources SET enabled=1,updated_at=CURRENT_TIMESTAMP WHERE (group_id=? OR (group_id IS NULL AND created_by=?))", (target_group, user["id"])); notice = "sources_enabled"
        elif action == "disable":
            db.execute("UPDATE welink_sources SET enabled=0,updated_at=CURRENT_TIMESTAMP WHERE (group_id=? OR (group_id IS NULL AND created_by=?))", (target_group, user["id"])); notice = "sources_disabled"
        elif action == "discussion":
            db.execute("UPDATE welink_sources SET enabled=CASE WHEN source_type='discussion_group' THEN 1 ELSE 0 END,updated_at=CURRENT_TIMESTAMP WHERE (group_id=? OR (group_id IS NULL AND created_by=?))", (target_group, user["id"])); notice = "sources_discussion"
        elif action == "delete":
            selected = sorted({int(value.strip()) for value in source_ids.split(",") if value.strip().isdigit() and int(value.strip()) > 0})
            if not selected:
                db.close()
                return redirect(_welink_redirect(error="source_selection", group_id=target_group, anchor="sources"))
            placeholders = ",".join("?" for _ in selected)
            db.execute(f"DELETE FROM welink_sources WHERE id IN ({placeholders}) AND (group_id=? OR (group_id IS NULL AND created_by=?))", [*selected, target_group, user["id"]])
            notice = "sources_deleted"
        else:
            db.close(); raise HTTPException(404)
        db.commit(); db.close(); return redirect(_welink_redirect(notice=notice, group_id=target_group, anchor="sources"))

    @app.post("/welink/sources/{source_id}/edit")
    def edit_source(request: Request, source_id: int, source_type: str = Form(), display_name: str = Form(), conversation_key: str = Form(), note: str = Form(""), lookback_days: int = Form(3)):
        user = require_user(request); db = connection(); source = db.execute("SELECT * FROM welink_sources WHERE id=?", (source_id,)).fetchone(); _manage(user, source, db)
        name, key, kind = _clean(display_name, 120), _clean(conversation_key, 160), _clean(source_type, 32)
        days = max(0, min(int(lookback_days or 0), 365))
        if not name or not key or kind not in SOURCE_TYPES: db.close(); return redirect(_welink_redirect(error="source", group_id=source["group_id"], anchor="sources"))
        if kind != "discussion_group" and days == 0: days = 3
        try:
            db.execute("UPDATE welink_sources SET source_type=?,display_name=?,conversation_key=?,note=?,lookback_days=?,updated_at=CURRENT_TIMESTAMP WHERE id=?", (kind, name, key, _clean(note, 500), days, source_id)); db.commit()
        except Exception:
            db.rollback(); db.close()
            return redirect(_welink_redirect(error="duplicate", group_id=source["group_id"], anchor="sources"))
        db.close()
        return redirect(_welink_redirect(notice="source_updated", group_id=source["group_id"], anchor="sources"))

    @app.post("/welink/sources/{source_id}/{action}")
    def manage_source(request: Request, source_id: int, action: str):
        user = require_user(request); db = connection(); source = db.execute("SELECT * FROM welink_sources WHERE id=?", (source_id,)).fetchone(); _manage(user, source, db)
        if action == "toggle":
            db.execute("UPDATE welink_sources SET enabled=1-enabled,updated_at=CURRENT_TIMESTAMP WHERE id=?", (source_id,))
            notice = "source_toggled"
        elif action == "delete":
            db.execute("DELETE FROM welink_sources WHERE id=?", (source_id,))
            notice = "source_deleted"
        else:
            db.close(); raise HTTPException(404)
        db.commit(); db.close(); return redirect(_welink_redirect(notice=notice, group_id=source["group_id"], anchor="sources"))

    @app.post("/welink/recipients")
    def create_recipient(request: Request, recipient_type: str = Form(), display_name: str = Form(), receiver_key: str = Form(), group_id: int = Form(0)):
        user = require_user(request)
        recipient_type, display_name, receiver_key = _clean(recipient_type, 20), _clean(display_name, 120), _clean(receiver_key, 160)
        if recipient_type not in RECIPIENT_TYPES or not display_name or not receiver_key:
            return redirect(_welink_redirect(error="recipient", group_id=group_id or None, anchor="recipients"))
        db = connection()
        target_group = _group_id_from_form(db, user, group_id or None)
        try:
            db.execute("INSERT INTO welink_recipients (recipient_type,display_name,receiver_key,created_by,group_id) VALUES (?,?,?,?,?)", (recipient_type, display_name, receiver_key, user["id"], target_group)); db.commit()
        except Exception:
            db.rollback(); return redirect(_welink_redirect(error="duplicate", group_id=target_group, anchor="recipients"))
        finally:
            db.close()
        return redirect(_welink_redirect(notice="recipient_created", group_id=target_group, anchor="recipients"))

    @app.post("/welink/recipients/{recipient_id}/edit")
    def edit_recipient(request: Request, recipient_id: int, recipient_type: str = Form(), display_name: str = Form(), receiver_key: str = Form()):
        user = require_user(request); db = connection(); item = db.execute("SELECT * FROM welink_recipients WHERE id=?", (recipient_id,)).fetchone(); _manage(user, item, db)
        name, key, kind = _clean(display_name, 120), _clean(receiver_key, 160), _clean(recipient_type, 20)
        if not name or not key or kind not in RECIPIENT_TYPES: db.close(); return redirect(_welink_redirect(error="recipient", group_id=item["group_id"], anchor="recipients"))
        try:
            db.execute("UPDATE welink_recipients SET recipient_type=?,display_name=?,receiver_key=? WHERE id=?", (kind, name, key, recipient_id)); db.commit()
        except Exception:
            db.rollback(); db.close()
            return redirect(_welink_redirect(error="duplicate", group_id=item["group_id"], anchor="recipients"))
        db.close()
        return redirect(_welink_redirect(notice="recipient_updated", group_id=item["group_id"], anchor="recipients"))

    @app.post("/welink/recipients/{recipient_id}/{action}")
    def manage_recipient(request: Request, recipient_id: int, action: str):
        user = require_user(request); db = connection(); item = db.execute("SELECT * FROM welink_recipients WHERE id=?", (recipient_id,)).fetchone(); _manage(user, item, db)
        if action == "toggle": db.execute("UPDATE welink_recipients SET enabled=1-enabled WHERE id=?", (recipient_id,)); notice = "recipient_toggled"
        elif action == "delete": db.execute("DELETE FROM welink_recipients WHERE id=?", (recipient_id,)); notice = "recipient_deleted"
        else: db.close(); raise HTTPException(404)
        db.commit(); db.close(); return redirect(_welink_redirect(notice=notice, group_id=item["group_id"], anchor="recipients"))

    @app.post("/welink/runs")
    def start_run(request: Request, group_id: int = Form(0)):
        user = require_user(request); db = connection()
        target_group = _group_id_from_form(db, user, group_id or None)
        sources = db.execute("SELECT id,source_type,display_name,conversation_key,note,lookback_days FROM welink_sources WHERE enabled=1 AND (group_id=? OR (group_id IS NULL AND created_by=?))", (target_group, user["id"])).fetchall()
        recipients = db.execute("SELECT id,recipient_type,display_name,receiver_key FROM welink_recipients WHERE enabled=1 AND (group_id=? OR (group_id IS NULL AND created_by=?))", (target_group, user["id"])).fetchall()
        mode = _mode(db)
        if mode == "demo":
            status, summary, progress, stage = "completed", "演示巡检已完成：已使用本地模拟消息生成任务记录，未连接 WeLink、未发送任何内容。", 100, "已完成"
        else:
            if db.execute("SELECT 1 FROM welink_runs WHERE (requested_by=? OR group_id=?) AND run_mode='production' AND status IN ('queued','awaiting_bridge') LIMIT 1", (user["id"], target_group)).fetchone():
                db.close()
                return redirect(_welink_redirect(error="run_active", group_id=target_group, anchor="runs"))
            if not sources:
                db.close()
                return redirect(_welink_redirect(error="no_sources", group_id=target_group, anchor="sources"))
            connector_enabled = os.getenv("WELINK_CONNECTOR_ENABLED", "0").strip().lower() in {"1", "true", "yes"}
            bridge_enabled = bool(os.getenv("WELINK_AGENT_BRIDGE_URL", "").strip() and os.getenv("WELINK_AGENT_BRIDGE_TOKEN", "").strip())
            if not bridge_enabled and not connector_enabled:
                db.close()
                return redirect(_welink_redirect(error="bridge", group_id=target_group, anchor="automation"))
            if bridge_enabled:
                status, summary = _bridge_run(sources, recipients, group_id=target_group)
                progress = 100 if status in {"completed", "failed"} else 35
                stage = {"completed": "已完成", "failed": "执行失败", "queued": "等待内网桥接处理"}.get(status, "等待内网桥接")
            else:
                status, summary, progress, stage = "queued", "已创建本地连接器任务，等待用户电脑领取。", 10, "等待本地连接器领取"
        run_id = db.execute("INSERT INTO welink_runs (status,source_count,recipient_count,summary,run_mode,progress,current_stage,requested_by,group_id) VALUES (?,?,?,?,?,?,?,?,?)", (status, len(sources), len(recipients), summary, mode, progress, stage, user["id"], target_group)).lastrowid
        if mode == "production" and not os.getenv("WELINK_AGENT_BRIDGE_URL", "").strip() and os.getenv("WELINK_CONNECTOR_ENABLED", "0").strip().lower() in {"1", "true", "yes"}:
            _enqueue_connector_job(db, user, target_group, sources, recipients, run_id=run_id, idempotency_key=f"run:{run_id}")
        db.commit(); db.close()
        return redirect(_welink_redirect(notice="run_completed" if status == "completed" else "run_queued", group_id=target_group, anchor="runs"))

    @app.post("/welink/issues/{issue_id}/status")
    def change_issue_status(request: Request, issue_id: int, status: str = Form()):
        user = require_user(request)
        if status not in {"处理中", "待协调", "待观察", "已闭环"}: raise HTTPException(400, "状态无效")
        db = connection(); groups = visible_group_ids(db, user); clause, params = scoped_in_clause("group_id", groups)
        issue = db.execute(f"SELECT * FROM welink_issues WHERE id=? AND (is_demo=1 OR {clause})", [issue_id, *params]).fetchone()
        if not issue:
            db.close(); raise HTTPException(404, "问题不存在或无权访问")
        if issue["is_demo"] and user["role"] != "admin":
            db.close(); raise HTTPException(403, "演示问题不可修改")
        group_id = issue["group_id"]
        db.execute("UPDATE welink_issues SET status=?,updated_at=CURRENT_TIMESTAMP WHERE id=?", (status, issue_id)); db.commit(); db.close()
        return redirect(_welink_redirect(notice="issue_updated", group_id=group_id, anchor="issues"))

    @app.post("/welink/actions/{action_id}/toggle")
    def toggle_action(request: Request, action_id: int):
        user = require_user(request); db = connection(); groups = visible_group_ids(db, user); clause, params = scoped_in_clause("i.group_id", groups)
        action = db.execute(f"SELECT a.*,i.is_demo,i.group_id FROM welink_issue_actions a JOIN welink_issues i ON i.id=a.issue_id WHERE a.id=? AND (i.is_demo=1 OR {clause})", [action_id, *params]).fetchone()
        if not action:
            db.close(); raise HTTPException(404, "行动项不存在或无权访问")
        if action["is_demo"] and user["role"] != "admin":
            db.close(); raise HTTPException(403, "演示行动项不可修改")
        group_id = action["group_id"]
        db.execute("UPDATE welink_issue_actions SET status=CASE WHEN status='已完成' THEN '待执行' ELSE '已完成' END,updated_at=CURRENT_TIMESTAMP WHERE id=?", (action_id,)); db.commit(); db.close()
        return redirect(_welink_redirect(notice="action_updated", group_id=group_id, anchor="issues"))

    @app.post("/welink/schedule")
    def save_schedule(request: Request, enabled: str = Form("0"), schedule_time: str = Form("08:00")):
        user = require_user(request); value = _clean(schedule_time, 5)
        if len(value) != 5 or value[2] != ":": raise HTTPException(400, "时间格式应为 HH:MM")
        db = connection(); group_id = _group_id_from_form(db, user, request.query_params.get("group_id") or None)
        db.execute("INSERT INTO welink_schedules (group_id,enabled,schedule_time,updated_by) VALUES (?,?,?,?) ON CONFLICT(group_id) DO UPDATE SET enabled=excluded.enabled,schedule_time=excluded.schedule_time,updated_by=excluded.updated_by,updated_at=CURRENT_TIMESTAMP", (group_id, 1 if enabled == "1" else 0, value, user["id"]))
        db.commit(); db.close()
        return redirect(f"/welink?group_id={group_id}&notice=schedule_saved#automation")

    @app.post("/welink/connectors/pair")
    def pair_connector(request: Request, device_name: str = Form("Windows 连接器")):
        """Enroll one user's Windows connector and show the token once."""
        user = require_user(request); db = connection()
        ensure_personal_group(db, user["id"])
        token = secrets.token_urlsafe(32)
        device_id = db.execute(
            "INSERT INTO welink_connector_devices (user_id,device_name,token_hash,capabilities) VALUES (?,?,?,?)",
            (user["id"], _clean(device_name, 120) or "Windows 连接器", _connector_token_hash(token), "[]"),
        ).lastrowid
        db.commit(); db.close()
        return JSONResponse({"device_id": device_id, "token": token, "warning": "令牌只显示这一次，请保存到 Windows 连接器的安全配置中。"})

    @app.post("/welink/connectors/{device_id}/revoke")
    def revoke_connector(request: Request, device_id: int):
        user = require_user(request); db = connection()
        device = db.execute("SELECT * FROM welink_connector_devices WHERE id=?", (device_id,)).fetchone()
        if not device:
            db.close(); raise HTTPException(404, "连接器不存在")
        if user["role"] != "admin" and device["user_id"] != user["id"]:
            db.close(); raise HTTPException(403, "只能撤销自己的连接器")
        db.execute("UPDATE welink_connector_devices SET status='revoked' WHERE id=?", (device_id,)); db.commit(); db.close()
        return redirect(_welink_redirect(notice="connector_revoked", anchor="automation"))

    @app.post("/api/welink/connectors/heartbeat")
    async def connector_heartbeat(request: Request):
        db = connection(); device = _connector_device(db, request); data = await request.json() if request.headers.get("content-type", "").startswith("application/json") else {}
        capabilities = data.get("capabilities") if isinstance(data, dict) else None
        if isinstance(capabilities, list):
            db.execute("UPDATE welink_connector_devices SET capabilities=? WHERE id=?", (json.dumps(capabilities[:30], ensure_ascii=False), device["id"]))
        db.commit(); db.close()
        return JSONResponse({"ok": True, "device_id": device["id"]})

    @app.get("/api/welink/connectors/jobs")
    def connector_next_job(request: Request):
        db = connection(); device = _connector_device(db, request)
        db.commit()
        db.execute("BEGIN IMMEDIATE")
        job = db.execute(
            "SELECT j.* FROM welink_jobs j JOIN welink_group_members m ON m.group_id=j.group_id WHERE m.user_id=? AND j.status='queued' ORDER BY j.created_at,j.id LIMIT 1",
            (device["user_id"],),
        ).fetchone()
        if not job:
            db.commit(); db.close(); return JSONResponse({"job": None})
        lease_token = secrets.token_urlsafe(20)
        db.execute("UPDATE welink_jobs SET status='leased',lease_token=?,lease_expires_at=datetime('now','+5 minutes'),attempts=attempts+1,updated_at=CURRENT_TIMESTAMP WHERE id=?", (lease_token, job["id"]))
        db.commit()
        payload = json.loads(job["payload"] or "{}")
        db.close()
        return JSONResponse({"job": {"id": job["id"], "run_id": job["run_id"], "type": job["job_type"], "lease_token": lease_token, "lease_seconds": 300, "payload": payload}})

    def _connector_job_for(db, request: Request, job_id: int):
        device = _connector_device(db, request)
        job = db.execute("SELECT j.* FROM welink_jobs j JOIN welink_group_members m ON m.group_id=j.group_id WHERE j.id=? AND m.user_id=?", (job_id, device["user_id"])).fetchone()
        if not job:
            raise HTTPException(404, "任务不存在或不属于当前连接器")
        if job["lease_expires_at"] and job["lease_token"]:
            expiry = datetime.fromisoformat(job["lease_expires_at"].replace("Z", "")) if "T" in job["lease_expires_at"] else datetime.strptime(job["lease_expires_at"], "%Y-%m-%d %H:%M:%S")
            if expiry and expiry < datetime.now(timezone.utc).replace(tzinfo=None):
                db.execute("UPDATE welink_jobs SET status='queued',lease_token=NULL,lease_expires_at=NULL,updated_at=CURRENT_TIMESTAMP WHERE id=?", (job_id,)); db.commit(); raise HTTPException(409, "任务租约已过期，请重新领取")
        return device, job

    @app.post("/api/welink/connectors/jobs/{job_id}/ack")
    async def connector_ack(request: Request, job_id: int):
        data = await request.json()
        state = str(data.get("state", "running")) if isinstance(data, dict) else "running"
        if state not in {"running", "completed", "failed", "cancelled"}:
            raise HTTPException(400, "任务状态无效")
        db = connection(); _, job = _connector_job_for(db, request, job_id)
        lease_token = str(data.get("lease_token", ""))
        if not lease_token or lease_token != job["lease_token"]:
            db.close(); raise HTTPException(409, "任务租约令牌不匹配")
        db.execute("UPDATE welink_jobs SET status=?,error=?,updated_at=CURRENT_TIMESTAMP WHERE id=?", (state, _clean(str(data.get("error", "")), 1000), job_id))
        if job["run_id"] and state in {"failed", "cancelled"}:
            db.execute("UPDATE welink_runs SET status='failed',progress=100,current_stage=?,summary=? WHERE id=?", ("执行失败" if state == "failed" else "已取消", _clean(str(data.get("error", "")), 1000), job["run_id"]))
        db.commit(); db.close(); return JSONResponse({"ok": True, "status": state})

    @app.post("/api/welink/connectors/jobs/{job_id}/result")
    async def connector_result(request: Request, job_id: int):
        data = await request.json()
        if not isinstance(data, dict):
            raise HTTPException(400, "结果必须是 JSON 对象")
        db = connection(); _, job = _connector_job_for(db, request, job_id)
        lease_token = str(data.get("lease_token", ""))
        if not lease_token or lease_token != job["lease_token"]:
            db.close(); raise HTTPException(409, "任务租约令牌不匹配")
        result = json.dumps(data, ensure_ascii=False)[:2_000_000]
        ok = bool(data.get("ok", True))
        if ok:
            _ingest_connector_result(db, job, data)
        db.execute("UPDATE welink_jobs SET status=?,result=?,error=?,updated_at=CURRENT_TIMESTAMP WHERE id=?", ("completed" if ok else "failed", result, _clean(str(data.get("error", "")), 1000), job_id))
        if job["run_id"]:
            db.execute("UPDATE welink_runs SET status=?,progress=100,current_stage=?,summary=? WHERE id=?", ("completed" if ok else "failed", "已完成" if ok else "执行失败", _clean(str(data.get("summary", "连接器已返回标准化结果。")), 1000), job["run_id"]))
        db.commit(); db.close(); return JSONResponse({"ok": True, "status": "completed" if ok else "failed"})

    @app.post("/welink/reports/generate")
    def generate_report(request: Request):
        user = require_user(request); db = connection(); mode = _mode(db); group_id = _group_id_from_form(db, user, request.query_params.get("group_id") or None); issues = _issue_context(db, include_demo=mode == "demo", group_ids=[group_id])
        heading = "## 巡检报告（演示数据）" if mode == "demo" else "## 巡检报告（生产桥接数据）"
        summary = heading + "\n\n" + ("\n".join(f"### [{x['severity']}] {x['title']}\n- **状态**：{x['status']}；责任人：{x['owner']}；截止：{x['due_at'] or '未设置'}\n- **背景**：{x['background']}\n- **最新进展**：{x['latest_progress']}\n- **根因/风险**：{x['root_cause'] or x['risk_reason']}\n- **下一步**：{x['next_step']}" for x in issues) or "尚未收到内网桥接服务返回的问题台账；未生成任何故障结论。")
        latest_run = db.execute("SELECT id FROM welink_runs WHERE (requested_by=? OR group_id=?) AND run_mode=? ORDER BY id DESC LIMIT 1", (user["id"], group_id, mode)).fetchone()
        db.execute("INSERT INTO welink_reports (run_id,run_mode,content,created_by,group_id) VALUES (?,?,?,?,?)", (latest_run["id"] if latest_run else None, mode, summary, user["id"], group_id)); db.commit(); db.close()
        return redirect(f"/welink?group_id={group_id}&notice=report_generated#reports")

    @app.post("/welink/chat/conversations")
    def new_welink_conversation(request: Request, group_id: int = 0):
        user = require_user(request)
        db = connection()
        target_group = _group_id_from_form(db, user, group_id or request.query_params.get("group_id") or None)
        conversation_id = create_conversation(db, user["id"], "welink", _mode(db), target_group)
        db.close()
        return redirect(f"/welink?group_id={target_group}&chat={conversation_id}#chat")

    @app.post("/welink/chat/conversations/{conversation_id}/rename")
    def rename_welink_conversation(request: Request, conversation_id: int, title: str = Form(""), group_id: int = Form(0)):
        user = require_user(request)
        db = connection()
        mode = _mode(db)
        target_group = _group_id_from_form(db, user, group_id or request.query_params.get("group_id") or None)
        try:
            renamed = rename_conversation(db, user["id"], conversation_id, "welink", title, mode, target_group)
        except ValueError as error:
            db.close()
            raise HTTPException(400, str(error))
        db.close()
        if not renamed:
            raise HTTPException(404, "对话不存在")
        return redirect(f"/welink?group_id={target_group}&chat={conversation_id}&notice=conversation_renamed#chat")

    @app.post("/welink/chat/stream")
    def welink_chat_stream(request: Request, question: str = Form(""), conversation_id: int = Form(0), group_id: int = Form(0)):
        user = require_user(request)
        if not question.strip(): raise HTTPException(400, "请输入问题")
        db = connection(); mode = _mode(db); group_id = _group_id_from_form(db, user, group_id or request.query_params.get("group_id") or None); issues = _issue_context(db, include_demo=mode == "demo", group_ids=[group_id])
        conversation = current_conversation(db, user["id"], "welink", conversation_id or None, mode, group_id)
        touch_conversation(db, conversation["id"], question)
        db.execute("INSERT INTO welink_chat_messages (user_id,conversation_id,role,content,group_id) VALUES (?,?,?,?,?)", (user["id"], conversation["id"], "user", _clean(question, 3000), group_id)); db.commit(); db.close()
        fallback = "## 基于当前巡检台账的建议\n\n" + "\n".join(f"- **{x['title']}**：{x['next_step']}（责任人：{x['owner']}）" for x in issues)
        context_label = "演示数据，不代表真实消息" if mode == "demo" else "生产桥接数据"
        prompt = "用户问题：" + question + f"\n\n当前 WeLink 巡检台账（{context_label}）：\n" + json.dumps([{k: x[k] for k in ('title','severity','status','background','latest_progress','root_cause','risk_reason','next_step','owner','due_at')} for x in issues], ensure_ascii=False)
        def record():
            chunks = []
            completed = False
            try:
                for chunk in (llm_provider(prompt, fallback) if llm_provider else [fallback]):
                    chunks.append(chunk)
                    yield chunk
                completed = True
            finally:
                content = "".join(chunks)
                if content:
                    if not completed:
                        if REASONING_START in content and REASONING_END not in content:
                            content += REASONING_END
                        content += "\n\n> 回答生成已中断。"
                    write_db = connection()
                    write_db.execute("INSERT INTO welink_chat_messages (user_id,conversation_id,role,content,group_id) VALUES (?,?,?,?,?)", (user["id"], conversation["id"], "assistant", content, group_id))
                    write_db.commit(); write_db.close()
        return StreamingResponse(record(), media_type="text/plain; charset=utf-8", headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})
