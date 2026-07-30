"""Safe configuration and audit boundary for the WeLink inspection module."""

import json
import os
import urllib.error
import urllib.request

from fastapi import Form, HTTPException, Request
from fastapi.responses import HTMLResponse, StreamingResponse

from .chat_sessions import conversation_list, create_conversation, current_conversation, rename_conversation, touch_conversation
from .database import connection
from .runtime_settings import get_setting, set_setting

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
    "conversation_renamed": "对话名称已更新。",
}
ERROR_MESSAGES = {
    "source": "消息源未保存，请检查类型、名称和群标识或工号。",
    "recipient": "接收方未保存，请检查类型、名称和群标识或工号。",
    "duplicate": "存在相同类型和标识的配置，请直接编辑原配置。",
    "no_sources": "生产巡检至少需要一个已启用的消息源。",
    "bridge": "生产巡检尚不可用：请先在服务器配置内网桥接地址和令牌。",
    "run_active": "已有生产巡检正在排队或等待桥接，请勿重复提交。",
}


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


def _issue_context(db, include_demo=True):
    sql = "SELECT * FROM welink_issues"
    if not include_demo:
        sql += " WHERE is_demo=0"
    issues = db.execute(sql + " ORDER BY CASE severity WHEN 'P1' THEN 1 WHEN 'P2' THEN 2 ELSE 3 END, updated_at DESC").fetchall()
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


def _manage(user, item):
    if not item:
        raise HTTPException(404, "配置不存在")
    if item["created_by"] != user["id"] and user["role"] != "admin":
        raise HTTPException(403, "只能管理自己创建的配置")


def _mode(db) -> str:
    return get_setting(db, "welink_run_mode", os.getenv("WELINK_DEFAULT_MODE", "demo").strip() or "demo")


def _bridge_run(sources, recipients):
    """Call the fixed in-network bridge contract; never invoke a shell command."""
    base_url = os.getenv("WELINK_AGENT_BRIDGE_URL", "").strip().rstrip("/")
    token = os.getenv("WELINK_AGENT_BRIDGE_TOKEN", "").strip()
    if not base_url or not token:
        return "awaiting_bridge", "生产模式尚未配置内网桥接地址或服务令牌，未读取或发送任何消息。"
    payload = {
        "sources": [dict(item) for item in sources],
        "recipients": [dict(item) for item in recipients],
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
    def welink_dashboard(request: Request, chat: int = 0):
        user = require_user(request)
        db = connection()
        mode = _mode(db)
        sources = db.execute("SELECT s.*,u.username FROM welink_sources s JOIN users u ON u.id=s.created_by WHERE s.created_by=? ORDER BY s.enabled DESC,s.updated_at DESC", (user["id"],)).fetchall()
        recipients = db.execute("SELECT r.*,u.username FROM welink_recipients r JOIN users u ON u.id=r.created_by WHERE r.created_by=? ORDER BY r.enabled DESC,r.created_at DESC", (user["id"],)).fetchall()
        runs = db.execute("SELECT r.*,u.username FROM welink_runs r JOIN users u ON u.id=r.requested_by WHERE r.requested_by=? ORDER BY r.created_at DESC LIMIT 8", (user["id"],)).fetchall()
        active_run = next((item for item in runs if item["run_mode"] == mode and item["status"] in {"queued", "awaiting_bridge"}), None)
        if mode == "demo": _seed_demo_issues(db); db.commit()
        issues = _issue_context(db, include_demo=mode == "demo")
        active_issue_count = sum(1 for item in issues if item["status"] != "已闭环")
        critical_issue_count = sum(1 for item in issues if item["severity"] == "P1" and item["status"] != "已闭环")
        pending_action_count = sum(1 for item in issues for action in item["actions"] if action["status"] != "已完成")
        report = db.execute(
            "SELECT * FROM welink_reports WHERE created_by=? AND run_mode=? ORDER BY id DESC LIMIT 1",
            (user["id"], mode),
        ).fetchone()
        active_conversation = current_conversation(db, user["id"], "welink", chat or None, mode)
        chat_history = db.execute(
            "SELECT role,content,created_at FROM welink_chat_messages WHERE user_id=? AND conversation_id=? ORDER BY id ASC LIMIT 100",
            (user["id"], active_conversation["id"]),
        ).fetchall()
        conversations = conversation_list(db, user["id"], "welink", mode)
        schedule_enabled = get_setting(db, "welink_schedule_enabled", "1") == "1"
        schedule_time = get_setting(db, "welink_schedule_time", "08:00")
        bridge_configured = bool(os.getenv("WELINK_AGENT_BRIDGE_URL", "").strip() and os.getenv("WELINK_AGENT_BRIDGE_TOKEN", "").strip())
        notice_message = NOTICE_MESSAGES.get(request.query_params.get("notice", ""))
        error_message = ERROR_MESSAGES.get(request.query_params.get("error", ""))
        db.close()
        return page(request, "welink.html", sources=sources, recipients=recipients, runs=runs, active_run=active_run, issues=issues, active_issue_count=active_issue_count, critical_issue_count=critical_issue_count, pending_action_count=pending_action_count, latest_report=report, chat_history=chat_history, conversations=conversations, active_conversation=active_conversation, schedule_enabled=schedule_enabled, schedule_time=schedule_time, source_types=SOURCE_TYPES, recipient_types=RECIPIENT_TYPES, bridge_configured=bridge_configured, production_ready=bridge_configured and any(item["enabled"] for item in sources), run_mode=mode, notice_message=notice_message, error_message=error_message, can_switch_mode=user["role"] == "admin" or os.getenv("APP_ENV", "development").strip().lower() != "production")

    @app.post("/welink/mode")
    def change_mode(request: Request, run_mode: str = Form()):
        user = require_user(request)
        if user["role"] != "admin" and os.getenv("APP_ENV", "development").strip().lower() == "production":
            raise HTTPException(403, "只有管理员可以切换运行模式")
        if run_mode not in {"demo", "production"}:
            raise HTTPException(400, "运行模式无效")
        db = connection(); set_setting(db, "welink_run_mode", run_mode, user["id"]); db.commit(); db.close()
        return redirect(f"/welink?notice=mode_{run_mode}")

    @app.post("/welink/sources")
    def create_source(request: Request, source_type: str = Form(), display_name: str = Form(), conversation_key: str = Form(), note: str = Form(""), lookback_days: int = Form(3)):
        user = require_user(request)
        source_type, display_name, conversation_key = _clean(source_type, 32), _clean(display_name, 120), _clean(conversation_key, 160)
        if source_type not in SOURCE_TYPES or not display_name or not conversation_key:
            return redirect("/welink?error=source")
        days = max(0, min(int(lookback_days or 0), 365))
        if source_type != "discussion_group" and days == 0:
            days = 3
        db = connection()
        try:
            db.execute("INSERT INTO welink_sources (source_type,display_name,conversation_key,note,lookback_days,created_by) VALUES (?,?,?,?,?,?)", (source_type, display_name, conversation_key, _clean(note, 500), days, user["id"]))
            db.commit()
        except Exception:
            db.rollback()
            return redirect("/welink?error=duplicate")
        finally:
            db.close()
        return redirect("/welink?notice=source_created#sources")

    @app.post("/welink/sources/{source_id}/{action}")
    def manage_source(request: Request, source_id: int, action: str):
        user = require_user(request); db = connection(); source = db.execute("SELECT * FROM welink_sources WHERE id=?", (source_id,)).fetchone(); _manage(user, source)
        if action == "toggle":
            db.execute("UPDATE welink_sources SET enabled=1-enabled,updated_at=CURRENT_TIMESTAMP WHERE id=?", (source_id,))
            notice = "source_toggled"
        elif action == "delete":
            db.execute("DELETE FROM welink_sources WHERE id=?", (source_id,))
            notice = "source_deleted"
        else:
            db.close(); raise HTTPException(404)
        db.commit(); db.close(); return redirect(f"/welink?notice={notice}#sources")

    @app.post("/welink/sources/{source_id}/edit")
    def edit_source(request: Request, source_id: int, source_type: str = Form(), display_name: str = Form(), conversation_key: str = Form(), note: str = Form(""), lookback_days: int = Form(3)):
        user = require_user(request); db = connection(); source = db.execute("SELECT * FROM welink_sources WHERE id=?", (source_id,)).fetchone(); _manage(user, source)
        name, key, kind = _clean(display_name, 120), _clean(conversation_key, 160), _clean(source_type, 32)
        days = max(0, min(int(lookback_days or 0), 365))
        if not name or not key or kind not in SOURCE_TYPES: db.close(); return redirect("/welink?error=source")
        if kind != "discussion_group" and days == 0: days = 3
        try:
            db.execute("UPDATE welink_sources SET source_type=?,display_name=?,conversation_key=?,note=?,lookback_days=?,updated_at=CURRENT_TIMESTAMP WHERE id=?", (kind, name, key, _clean(note, 500), days, source_id)); db.commit()
        except Exception:
            db.rollback(); db.close()
            return redirect("/welink?error=duplicate#sources")
        db.close()
        return redirect("/welink?notice=source_updated#sources")

    @app.post("/welink/sources/bulk/{action}")
    def bulk_sources(request: Request, action: str):
        user = require_user(request); db = connection()
        if action == "enable": db.execute("UPDATE welink_sources SET enabled=1,updated_at=CURRENT_TIMESTAMP WHERE created_by=?", (user["id"],)); notice = "sources_enabled"
        elif action == "disable": db.execute("UPDATE welink_sources SET enabled=0,updated_at=CURRENT_TIMESTAMP WHERE created_by=?", (user["id"],)); notice = "sources_disabled"
        elif action == "discussion": db.execute("UPDATE welink_sources SET enabled=CASE WHEN source_type='discussion_group' THEN 1 ELSE 0 END,updated_at=CURRENT_TIMESTAMP WHERE created_by=?", (user["id"],)); notice = "sources_discussion"
        else: db.close(); raise HTTPException(404)
        db.commit(); db.close(); return redirect(f"/welink?notice={notice}#sources")

    @app.post("/welink/recipients")
    def create_recipient(request: Request, recipient_type: str = Form(), display_name: str = Form(), receiver_key: str = Form()):
        user = require_user(request)
        recipient_type, display_name, receiver_key = _clean(recipient_type, 20), _clean(display_name, 120), _clean(receiver_key, 160)
        if recipient_type not in RECIPIENT_TYPES or not display_name or not receiver_key:
            return redirect("/welink?error=recipient")
        db = connection()
        try:
            db.execute("INSERT INTO welink_recipients (recipient_type,display_name,receiver_key,created_by) VALUES (?,?,?,?)", (recipient_type, display_name, receiver_key, user["id"])); db.commit()
        except Exception:
            db.rollback(); return redirect("/welink?error=duplicate")
        finally:
            db.close()
        return redirect("/welink?notice=recipient_created#recipients")

    @app.post("/welink/recipients/{recipient_id}/{action}")
    def manage_recipient(request: Request, recipient_id: int, action: str):
        user = require_user(request); db = connection(); item = db.execute("SELECT * FROM welink_recipients WHERE id=?", (recipient_id,)).fetchone(); _manage(user, item)
        if action == "toggle": db.execute("UPDATE welink_recipients SET enabled=1-enabled WHERE id=?", (recipient_id,)); notice = "recipient_toggled"
        elif action == "delete": db.execute("DELETE FROM welink_recipients WHERE id=?", (recipient_id,)); notice = "recipient_deleted"
        else: db.close(); raise HTTPException(404)
        db.commit(); db.close(); return redirect(f"/welink?notice={notice}#recipients")

    @app.post("/welink/recipients/{recipient_id}/edit")
    def edit_recipient(request: Request, recipient_id: int, recipient_type: str = Form(), display_name: str = Form(), receiver_key: str = Form()):
        user = require_user(request); db = connection(); item = db.execute("SELECT * FROM welink_recipients WHERE id=?", (recipient_id,)).fetchone(); _manage(user, item)
        name, key, kind = _clean(display_name, 120), _clean(receiver_key, 160), _clean(recipient_type, 20)
        if not name or not key or kind not in RECIPIENT_TYPES: db.close(); return redirect("/welink?error=recipient#recipients")
        try:
            db.execute("UPDATE welink_recipients SET recipient_type=?,display_name=?,receiver_key=? WHERE id=?", (kind, name, key, recipient_id)); db.commit()
        except Exception:
            db.rollback(); db.close()
            return redirect("/welink?error=duplicate#recipients")
        db.close()
        return redirect("/welink?notice=recipient_updated#recipients")

    @app.post("/welink/runs")
    def start_run(request: Request):
        user = require_user(request); db = connection()
        sources = db.execute("SELECT id,source_type,display_name,conversation_key,note,lookback_days FROM welink_sources WHERE enabled=1 AND created_by=?", (user["id"],)).fetchall()
        recipients = db.execute("SELECT id,recipient_type,display_name,receiver_key FROM welink_recipients WHERE enabled=1 AND created_by=?", (user["id"],)).fetchall()
        mode = _mode(db)
        if mode == "demo":
            status, summary, progress, stage = "completed", "演示巡检已完成：已使用本地模拟消息生成任务记录，未连接 WeLink、未发送任何内容。", 100, "已完成"
        else:
            if db.execute("SELECT 1 FROM welink_runs WHERE requested_by=? AND run_mode='production' AND status IN ('queued','awaiting_bridge') LIMIT 1", (user["id"],)).fetchone():
                db.close()
                return redirect("/welink?error=run_active#runs")
            if not sources:
                db.close()
                return redirect("/welink?error=no_sources")
            if not os.getenv("WELINK_AGENT_BRIDGE_URL", "").strip() or not os.getenv("WELINK_AGENT_BRIDGE_TOKEN", "").strip():
                db.close()
                return redirect("/welink?error=bridge")
            status, summary = _bridge_run(sources, recipients)
            progress = 100 if status in {"completed", "failed"} else 35
            stage = {"completed": "已完成", "failed": "执行失败", "queued": "等待内网桥接处理"}.get(status, "等待内网桥接")
        db.execute("INSERT INTO welink_runs (status,source_count,recipient_count,summary,run_mode,progress,current_stage,requested_by) VALUES (?,?,?,?,?,?,?,?)", (status, len(sources), len(recipients), summary, mode, progress, stage, user["id"])); db.commit(); db.close()
        return redirect(f"/welink?notice={'run_completed' if status == 'completed' else 'run_queued'}#runs")

    @app.post("/welink/issues/{issue_id}/status")
    def change_issue_status(request: Request, issue_id: int, status: str = Form()):
        require_user(request)
        if status not in {"处理中", "待协调", "待观察", "已闭环"}: raise HTTPException(400, "状态无效")
        db = connection(); db.execute("UPDATE welink_issues SET status=?,updated_at=CURRENT_TIMESTAMP WHERE id=?", (status, issue_id)); db.commit(); db.close()
        return redirect("/welink?notice=issue_updated#issues")

    @app.post("/welink/actions/{action_id}/toggle")
    def toggle_action(request: Request, action_id: int):
        require_user(request); db = connection()
        db.execute("UPDATE welink_issue_actions SET status=CASE WHEN status='已完成' THEN '待执行' ELSE '已完成' END,updated_at=CURRENT_TIMESTAMP WHERE id=?", (action_id,)); db.commit(); db.close()
        return redirect("/welink?notice=action_updated#issues")

    @app.post("/welink/schedule")
    def save_schedule(request: Request, enabled: str = Form("0"), schedule_time: str = Form("08:00")):
        user = require_user(request); value = _clean(schedule_time, 5)
        if len(value) != 5 or value[2] != ":": raise HTTPException(400, "时间格式应为 HH:MM")
        db = connection(); set_setting(db, "welink_schedule_enabled", "1" if enabled == "1" else "0", user["id"]); set_setting(db, "welink_schedule_time", value, user["id"]); db.commit(); db.close()
        return redirect("/welink?notice=schedule_saved#automation")

    @app.post("/welink/reports/generate")
    def generate_report(request: Request):
        user = require_user(request); db = connection(); mode = _mode(db); issues = _issue_context(db, include_demo=mode == "demo")
        heading = "## 巡检报告（演示数据）" if mode == "demo" else "## 巡检报告（生产桥接数据）"
        summary = heading + "\n\n" + ("\n".join(f"### [{x['severity']}] {x['title']}\n- **状态**：{x['status']}；责任人：{x['owner']}；截止：{x['due_at'] or '未设置'}\n- **背景**：{x['background']}\n- **最新进展**：{x['latest_progress']}\n- **根因/风险**：{x['root_cause'] or x['risk_reason']}\n- **下一步**：{x['next_step']}" for x in issues) or "尚未收到内网桥接服务返回的问题台账；未生成任何故障结论。")
        latest_run = db.execute("SELECT id FROM welink_runs WHERE requested_by=? AND run_mode=? ORDER BY id DESC LIMIT 1", (user["id"], mode)).fetchone()
        db.execute("INSERT INTO welink_reports (run_id,run_mode,content,created_by) VALUES (?,?,?,?)", (latest_run["id"] if latest_run else None, mode, summary, user["id"])); db.commit(); db.close()
        return redirect("/welink?notice=report_generated#reports")

    @app.post("/welink/chat/conversations")
    def new_welink_conversation(request: Request):
        user = require_user(request)
        db = connection()
        conversation_id = create_conversation(db, user["id"], "welink", _mode(db))
        db.close()
        return redirect(f"/welink?chat={conversation_id}#chat")

    @app.post("/welink/chat/conversations/{conversation_id}/rename")
    def rename_welink_conversation(request: Request, conversation_id: int, title: str = Form("")):
        user = require_user(request)
        db = connection()
        mode = _mode(db)
        try:
            renamed = rename_conversation(db, user["id"], conversation_id, "welink", title, mode)
        except ValueError as error:
            db.close()
            raise HTTPException(400, str(error))
        db.close()
        if not renamed:
            raise HTTPException(404, "对话不存在")
        return redirect(f"/welink?chat={conversation_id}&notice=conversation_renamed#chat")

    @app.post("/welink/chat/stream")
    def welink_chat_stream(request: Request, question: str = Form(""), conversation_id: int = Form(0)):
        user = require_user(request)
        if not question.strip(): raise HTTPException(400, "请输入问题")
        db = connection(); mode = _mode(db); issues = _issue_context(db, include_demo=mode == "demo")
        conversation = current_conversation(db, user["id"], "welink", conversation_id or None, mode)
        touch_conversation(db, conversation["id"], question)
        db.execute("INSERT INTO welink_chat_messages (user_id,conversation_id,role,content) VALUES (?,?,?,?)", (user["id"], conversation["id"], "user", _clean(question, 3000))); db.commit(); db.close()
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
                    write_db.execute("INSERT INTO welink_chat_messages (user_id,conversation_id,role,content) VALUES (?,?,?,?)", (user["id"], conversation["id"], "assistant", content))
                    write_db.commit(); write_db.close()
        return StreamingResponse(record(), media_type="text/plain; charset=utf-8", headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})
