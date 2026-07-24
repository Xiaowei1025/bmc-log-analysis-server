import json
import os
import re
import secrets
import urllib.error
import urllib.request
from pathlib import Path
from typing import Iterator, Optional

from fastapi import File, Form, HTTPException, Request, UploadFile
from fastapi.responses import FileResponse, HTMLResponse, RedirectResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from fastapi import FastAPI
from starlette.middleware.sessions import SessionMiddleware
from markupsafe import Markup

from .database import connection, init_db
from .bmc_skill_adapter import run_bmc_skill
from .case_importer import CaseImportError, SUPPORTED_SUFFIXES, extract_case_document, format_label as case_import_format_label, suggested_summary, suggested_title
from .log_parser import find_evidence, read_log_bundle
from .security import hash_password, verify_password

ROOT = Path(__file__).resolve().parents[1]


def load_local_env():
    """Load local deployment settings without requiring an extra dependency.

    Existing process environment variables win, so systemd/Docker can override
    values in .env. The file remains ignored by Git and release packaging.
    """
    env_file = ROOT / ".env"
    if not env_file.exists():
        return
    for raw in env_file.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        os.environ.setdefault(key.strip(), value.strip().strip('"').strip("'"))


load_local_env()
UPLOAD_DIR = ROOT / "uploads"
MAX_UPLOAD_BYTES = int(os.getenv("MAX_UPLOAD_MB", "200")) * 1024 * 1024
DEFAULT_APP_SECRET = "development-only-change-before-production"
KNOWN_UNSAFE_APP_SECRETS = {"", DEFAULT_APP_SECRET, "change-this-before-production", "replace-with-a-long-random-secret"}
VALID_ROLES = {"contributor", "reviewer", "admin"}
ROLE_LABELS = {"contributor": "贡献者", "reviewer": "审核者", "admin": "管理员"}
CSRF_SCAN_LIMIT = 64 * 1024
CSRF_URLENCODED_PATTERN = re.compile(br"(?:^|&)csrf_token=([^&\r\n]+)")
CSRF_MULTIPART_PATTERN = re.compile(br'name="csrf_token"[^\r\n]*\r\n(?:[^\r\n]*\r\n)*?\r\n([^\r\n]+)')


def env_flag(name: str, default: bool = False) -> bool:
    return os.getenv(name, str(default)).strip().lower() in {"1", "true", "yes", "on"}


def is_production() -> bool:
    return os.getenv("APP_ENV", "development").strip().lower() in {"production", "prod"}


def self_registration_enabled() -> bool:
    return env_flag("ALLOW_SELF_REGISTRATION", False)


def session_https_only() -> bool:
    return env_flag("SESSION_HTTPS_ONLY", is_production())


def production_secret_is_safe(value: str | None = None) -> bool:
    secret = os.getenv("APP_SECRET", DEFAULT_APP_SECRET) if value is None else value
    return bool(secret and len(secret) >= 32 and secret not in KNOWN_UNSAFE_APP_SECRETS)
HELP = {
    "dashboard.html": ("看板帮助", "看板汇总平台中的上传日志、已完成分析、特征和高严重度问题。点击最新报告可查看每个日志包的证据与 AI 分析。"),
    "logs.html": ("批量分析帮助", "可同时选择多个 tar.gz、zip、tar、gz 或单个文本日志。每个文件会生成一份独立报告，互不覆盖。"),
    "reports.html": ("报告帮助", "报告保存原始上传记录、自动命中特征和日志证据。可打开详情补充关联特征，或请求流式 LLM 分析。"),
    "report_detail.html": ("报告详情帮助", "自动命中特征来自规则扫描。也可将本报告手动关联到其他已知特征；关联不会修改原始日志。"),
    "features.html": ("特征库帮助", "特征是可复用的问题判定规则。每条规则包含名称、严重程度、关键词、描述、建议和一个或多个日志条件。"),
    "feature_form.html": ("编辑特征帮助", "每次保存都会生成一个规则版本。编辑已有规则后，系统会按新版本重新检查已完成的日志报告；旧版本命中会保留为可追溯历史。"),
    "feature_detail.html": ("特征详情帮助", "此页展示特征的当前规则、来源复核和关联日志。创建者可按当前规则重新检查历史报告；删除特征不会删除已上传日志。"),
    "feature_assist.html": ("AI 复核帮助", "上传来源日志后，系统会从实际日志重新提取每一条规则条件的文件、行号和片段，再由 AI 提出确认问题。最终判断由维护人员完成。"),
    "knowledge_cases.html": ("案例库帮助", "案例可新建，也可导入已有的 Word、PowerPoint、Markdown 或文本资料后再校对发布。案例正文会参与智能问答检索，并可被特征规则引用。"),
    "knowledge_case_import.html": ("导入案例帮助", "导入资料会先生成待发布草稿，原文件将被保留用于追溯。请校对自动提取的标题、摘要和正文，再补充日志或编辑细节后发布。DOCX、PPTX、Markdown 和文本可直接导入；旧版 DOC/PPT 需要服务器安装 LibreOffice。"),
    "knowledge_case_form.html": ("发布案例帮助", "正文默认使用富文本，可随时切换为 Markdown；两种模式都可使用上方格式工具栏。Markdown 中选中文本后可点“粗体”，或按 ⌘/Ctrl+B 插入/取消加粗；Markdown 模式还提供语法说明和实时预览。也可先导入已有文档生成草稿。两种方式均会安全沉淀为 Markdown，便于检索、问答与长期留存。可选上传一份或多份关联日志，每份日志会生成独立报告并与该案例关联。"),
    "knowledge_case_detail.html": ("案例详情帮助", "可阅读案例正文、查看关联日志报告、原始导入资料及被引用的特征。案例内容会作为内部知识补充给智能问答。"),
    "requests.html": ("需求板帮助", "所有登录用户都可查看和提交需求。团队按设定节奏集中评审，状态与评审意见会在需求详情中保留。"),
    "request_form.html": ("提交需求帮助", "请说明希望解决的痛点、使用场景和预期价值。需求会先进入待评审队列，避免直接承诺实现时间。"),
    "request_detail.html": ("需求详情帮助", "查看需求完整描述、当前状态与评审时间线。仅配置的评审人可以改变状态或添加评审意见。"),
    "ask.html": ("智能问答帮助", "问题会先从本地特征库检索相关知识，再由已配置的 LLM 流式生成建议。不要在问题中粘贴密码、密钥或未脱敏的敏感日志。"),
    "tools.html": ("工具中心帮助", "此模块保留原有的内部工具分发功能。工具作者可持续发布版本，历史版本和下载计数都会保留。"),
    "tool_form.html": ("发布工具帮助", "填写工具说明、版本和附件。请只上传已通过公司安全审核的内部工具。"),
    "tool_detail.html": ("工具详情帮助", "可下载各版本、查看历史、提交使用建议；仅工具作者可修改介绍或发布新版本。"),
    "tool_edit.html": ("修改工具帮助", "此页仅更新工具介绍或 Logo，不会删除历史版本或下载记录。"),
    "auth.html": ("账号帮助", "请使用内部团队约定的用户名注册。生产部署前建议接入公司统一身份认证。"),
}

app = FastAPI(title="BMC 智能日志平台")
app.mount("/static", StaticFiles(directory=ROOT / "app/static"), name="static")
templates = Jinja2Templates(directory=str(ROOT / "app/templates"))


@app.on_event("startup")
def startup():
    if is_production() and not production_secret_is_safe():
        raise RuntimeError("生产环境必须通过 APP_SECRET 设置随机会话密钥")
    if is_production() and not session_https_only():
        raise RuntimeError("生产环境必须启用 SESSION_HTTPS_ONLY=true，并由 HTTPS 反向代理提供服务")
    UPLOAD_DIR.mkdir(exist_ok=True)
    for folder in ("logs", "tools", "logos", "case-imports"):
        (UPLOAD_DIR / folder).mkdir(exist_ok=True)
    init_db()


def current_user(request: Request):
    user_id = request.session.get("user_id")
    if not user_id:
        return None
    db = connection()
    user = db.execute("SELECT id, username, role FROM users WHERE id = ?", (user_id,)).fetchone()
    db.close()
    return user


def page(request: Request, name: str, **context):
    context["user"] = current_user(request)
    context["csrf_token"] = ensure_csrf_token(request)
    context["registration_enabled"] = self_registration_enabled()
    context["role_label"] = role_label
    context.setdefault("help_title", HELP.get(name, ("页面帮助", "请根据页面上的提示完成操作。"))[0])
    context.setdefault("help_text", HELP.get(name, ("页面帮助", "请根据页面上的提示完成操作。"))[1])
    return templates.TemplateResponse(request=request, name=name, context=context)


def require_user(request: Request):
    user = current_user(request)
    if not user:
        raise HTTPException(status_code=401, detail="请先登录")
    return user


def role_label(user_or_role) -> str:
    if hasattr(user_or_role, "keys"):
        role = user_or_role["role"]
    elif isinstance(user_or_role, str):
        role = user_or_role
    else:
        role = getattr(user_or_role, "role", "contributor")
    return ROLE_LABELS.get(role, "贡献者")


def has_role(user, *roles: str) -> bool:
    return bool(user and user["role"] in roles)


def can_review_features(user, feature=None) -> bool:
    return bool(user and (has_role(user, "reviewer", "admin") or (feature and feature["created_by"] == user["id"])))


def can_manage_feature(user, feature) -> bool:
    return bool(user and (feature["created_by"] == user["id"] or has_role(user, "admin")))


def can_access_report_source(user, report) -> bool:
    return bool(user and (report["created_by"] == user["id"] or has_role(user, "reviewer", "admin")))


def can_access_case_import_source(user, imported_document) -> bool:
    return bool(
        user
        and (
            imported_document["imported_by"] == user["id"]
            or imported_document["case_created_by"] == user["id"]
            or has_role(user, "reviewer", "admin")
        )
    )


def ensure_csrf_token(request: Request) -> str:
    token = request.session.get("csrf_token")
    if not token:
        token = secrets.token_urlsafe(32)
        request.session["csrf_token"] = token
    return token


def csrf_input(request: Request) -> Markup:
    return Markup(f'<input type="hidden" name="csrf_token" value="{ensure_csrf_token(request)}">')


templates.env.globals["csrf_input"] = csrf_input
templates.env.globals["role_label"] = role_label


def csrf_token_matches(expected, submitted) -> bool:
    return bool(expected and submitted and secrets.compare_digest(str(expected), str(submitted)))


def csrf_token_from_body(content_type: bytes, body: bytes) -> str | None:
    pattern = CSRF_MULTIPART_PATTERN if b"multipart/form-data" in content_type.lower() else CSRF_URLENCODED_PATTERN
    match = pattern.search(body)
    if not match:
        return None
    return match.group(1).decode("utf-8", errors="ignore")


class CSRFSecurityMiddleware:
    """Validate a form token without consuming the upload stream downstream.

    The token is inserted as the first form field.  Only the first 64 KiB is
    inspected; buffered ASGI messages are replayed verbatim to FastAPI, so a
    large log upload keeps the application's original streaming behaviour.
    """

    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        async def send_with_security_headers(message):
            if message["type"] == "http.response.start":
                protected = {
                    b"x-content-type-options": b"nosniff",
                    b"x-frame-options": b"DENY",
                    b"referrer-policy": b"same-origin",
                    b"permissions-policy": b"camera=(), microphone=(), geolocation=()",
                }
                existing = {name.lower() for name, _ in message.get("headers", [])}
                message = dict(message)
                message["headers"] = list(message.get("headers", [])) + [
                    (name, value) for name, value in protected.items() if name not in existing
                ]
            await send(message)

        if scope["method"] not in {"POST", "PUT", "PATCH", "DELETE"}:
            await self.app(scope, receive, send_with_security_headers)
            return

        headers = {name.lower(): value for name, value in scope.get("headers", [])}
        expected = scope.get("session", {}).get("csrf_token")
        submitted = headers.get(b"x-csrf-token", b"").decode("utf-8", errors="ignore")
        buffered, inspected = [], bytearray()
        while not csrf_token_matches(expected, submitted):
            message = await receive()
            if message["type"] != "http.request":
                await self._reject(send_with_security_headers)
                return
            buffered.append(message)
            inspected.extend(message.get("body", b""))
            submitted = csrf_token_from_body(headers.get(b"content-type", b""), bytes(inspected))
            if len(inspected) >= CSRF_SCAN_LIMIT or not message.get("more_body", False):
                if not csrf_token_matches(expected, submitted):
                    await self._reject(send_with_security_headers)
                    return

        async def replay_receive():
            if buffered:
                return buffered.pop(0)
            return await receive()

        await self.app(scope, replay_receive, send_with_security_headers)

    @staticmethod
    async def _reject(send):
        await send({"type": "http.response.start", "status": 403, "headers": [(b"content-type", b"text/plain; charset=utf-8")]})
        await send({"type": "http.response.body", "body": "请求已被安全保护拒绝，请刷新页面后重试。".encode("utf-8")})


# Session middleware must wrap the CSRF middleware so the latter can read the
# signed session token before every state-changing request.
app.add_middleware(CSRFSecurityMiddleware)
app.add_middleware(
    SessionMiddleware,
    secret_key=os.getenv("APP_SECRET", DEFAULT_APP_SECRET),
    https_only=session_https_only(),
    same_site="lax",
)


def redirect(path: str):
    return RedirectResponse(path, status_code=303)


def save_upload(upload: UploadFile, folder: str) -> tuple[Path, str]:
    safe_name = Path(upload.filename or "upload.bin").name
    target = UPLOAD_DIR / folder / f"{secrets.token_hex(12)}_{safe_name}"
    written = 0
    with target.open("wb") as output:
        while chunk := upload.file.read(1024 * 1024):
            written += len(chunk)
            if written > MAX_UPLOAD_BYTES:
                target.unlink(missing_ok=True)
                raise HTTPException(413, f"文件超过 {MAX_UPLOAD_BYTES // 1024 // 1024} MB 限制")
            output.write(chunk)
    return target, safe_name


def severity_label(value: str) -> str:
    return {"critical": "严重", "high": "高", "medium": "中", "low": "低"}.get(value, "中")


def requirement_status_label(value: str) -> str:
    return {"pending": "待评审", "accepted": "已采纳", "planned": "规划中", "implemented": "已实现", "declined": "暂不处理"}.get(value, "待评审")


def requirement_category_label(value: str) -> str:
    return {"feature": "功能建议", "workflow": "流程优化", "ui": "界面体验", "knowledge": "知识内容", "other": "其他"}.get(value, "其他")


def requirement_review_cadence() -> str:
    return os.getenv("REQUEST_REVIEW_CADENCE", "每周").strip() or "每周"


def can_review_requirements(user) -> bool:
    reviewers = {name.strip() for name in os.getenv("REQUEST_REVIEWERS", "demo-maintainer").split(",") if name.strip()}
    return bool(user and (has_role(user, "reviewer", "admin") or user["username"] in reviewers))


def evaluate_feature_conditions(files: dict[str, str], conditions, match_mode: str):
    """Evaluate every condition and retain enough deterministic evidence for review."""
    evidence_items, matched = [], []
    for condition in conditions:
        found, error = find_evidence(files, condition["file_pattern"], condition["expression"], bool(condition["is_regex"]))
        item = {"condition": dict(condition), "found": found}
        if error:
            item["error"] = error
        evidence_items.append(item)
        matched.append(bool(found))
    is_hit = bool(matched) and (all(matched) if match_mode == "all" else any(matched))
    return evidence_items, is_hit


def scan_features(db, files: dict[str, str]):
    hits = []
    for feature in db.execute("SELECT * FROM cases ORDER BY CASE severity WHEN 'critical' THEN 1 WHEN 'high' THEN 2 WHEN 'medium' THEN 3 ELSE 4 END, id").fetchall():
        conditions = db.execute("SELECT * FROM case_conditions WHERE case_id=?", (feature["id"],)).fetchall()
        condition_evidence, is_hit = evaluate_feature_conditions(files, conditions, feature["match_mode"])
        if is_hit:
            hits.append({"feature": dict(feature), "evidence": condition_evidence, "total_conditions": len(conditions)})
    return hits


def create_analysis(db, user_id: int, stored: Path, original_name: str):
    try:
        files = read_log_bundle(stored)
        hits = scan_features(db, files)
        skill_result = run_bmc_skill(files, stored)
        summary = {
            "file_count": len(files),
            "match_count": len(hits),
            "skill_name": skill_result["skill_name"],
            "skill_version": skill_result["skill_version"],
            "skill_finding_count": len(skill_result["findings"]),
            "skill_warning": skill_result["warning"],
        }
        cursor = db.execute(
            "INSERT INTO analyses (original_name,storage_path,summary,status,file_count,match_count,created_by) VALUES (?,?,?,?,?,?,?)",
            (original_name, str(stored), json.dumps(summary, ensure_ascii=False), "completed", len(files), len(hits), user_id),
        )
        analysis_id = cursor.lastrowid
        for hit in hits:
            db.execute(
                "INSERT INTO analysis_matches (analysis_id,case_id,feature_version,evidence) VALUES (?,?,?,?)",
                (analysis_id, hit["feature"]["id"], hit["feature"]["rule_version"], json.dumps(hit["evidence"], ensure_ascii=False)),
            )
            db.execute("INSERT OR IGNORE INTO feature_log_links (case_id,analysis_id,relation_type,linked_by) VALUES (?,?,?,?)", (hit["feature"]["id"], analysis_id, "automatic", user_id))
        for finding in skill_result["findings"]:
            db.execute(
                """INSERT OR REPLACE INTO analysis_skill_findings
                (analysis_id,skill_name,skill_version,rule_id,title,severity,summary,diagnosis,solution,evidence,metadata)
                VALUES (?,?,?,?,?,?,?,?,?,?,?)""",
                (
                    analysis_id, skill_result["skill_name"], skill_result["skill_version"], finding["rule_id"],
                    finding["title"], finding["severity"], finding["summary"], finding["diagnosis"],
                    finding["solution"], json.dumps(finding["evidence"], ensure_ascii=False),
                    json.dumps(finding["metadata"], ensure_ascii=False),
                ),
            )
        return {"id": analysis_id, "original_name": original_name, "file_count": len(files), "match_count": len(hits), "status": "completed", "hits": hits, "skill_findings": skill_result["findings"], "skill_warning": skill_result["warning"]}
    except Exception as error:
        cursor = db.execute(
            "INSERT INTO analyses (original_name,storage_path,summary,status,created_by) VALUES (?,?,?,?,?)",
            (original_name, str(stored), json.dumps({"error": str(error)}, ensure_ascii=False), "failed", user_id),
        )
        return {"id": cursor.lastrowid, "original_name": original_name, "file_count": 0, "match_count": 0, "status": "failed", "error": str(error), "hits": []}


@app.get("/", response_class=HTMLResponse)
def dashboard(request: Request):
    require_user(request)
    db = connection()
    stats = {
        "uploaded": db.execute("SELECT COUNT(*) FROM analyses").fetchone()[0],
        "completed": db.execute("SELECT COUNT(*) FROM analyses WHERE status='completed'").fetchone()[0],
        "features": db.execute("SELECT COUNT(*) FROM cases").fetchone()[0],
        "critical": db.execute("SELECT COUNT(*) FROM cases WHERE severity IN ('critical','high')").fetchone()[0],
        "matched": db.execute("SELECT COUNT(*) FROM analysis_matches m JOIN cases c ON c.id=m.case_id AND c.rule_version=m.feature_version").fetchone()[0],
    }
    reports = db.execute("SELECT a.*,u.username FROM analyses a JOIN users u ON u.id=a.created_by ORDER BY a.created_at DESC LIMIT 6").fetchall()
    features = db.execute("SELECT c.*,u.username FROM cases c JOIN users u ON u.id=c.created_by ORDER BY c.updated_at DESC LIMIT 5").fetchall()
    contributors = db.execute(
        """SELECT u.username,COUNT(DISTINCT f.id) feature_count,COUNT(DISTINCT k.id) knowledge_case_count
        FROM users u LEFT JOIN cases f ON f.created_by=u.id
        LEFT JOIN knowledge_cases k ON k.created_by=u.id
        GROUP BY u.id HAVING COUNT(DISTINCT f.id)>0 OR COUNT(DISTINCT k.id)>0
        ORDER BY (COUNT(DISTINCT f.id)+COUNT(DISTINCT k.id)) DESC,COUNT(DISTINCT f.id) DESC,COUNT(DISTINCT k.id) DESC,u.username LIMIT 8"""
    ).fetchall()
    db.close()
    return page(request, "dashboard.html", stats=stats, reports=reports, features=features, contributors=contributors, severity_label=severity_label)


@app.get("/register")
def register_form(request: Request):
    if not self_registration_enabled():
        raise HTTPException(404)
    return page(request, "auth.html", mode="register")


@app.post("/register")
def register(request: Request, username: str = Form(), password: str = Form()):
    if not self_registration_enabled():
        raise HTTPException(404)
    username = username.strip()
    if len(username) < 2 or len(password) < 8:
        return page(request, "auth.html", mode="register", error="用户名至少 2 位，密码至少 8 位。")
    db = connection()
    try:
        cursor = db.execute("INSERT INTO users (username,password_hash) VALUES (?,?)", (username, hash_password(password)))
        db.commit()
        request.session.clear()
        request.session["user_id"] = cursor.lastrowid
        request.session["csrf_token"] = secrets.token_urlsafe(32)
        return redirect("/")
    except Exception:
        return page(request, "auth.html", mode="register", error="该用户名已存在。")
    finally:
        db.close()


@app.get("/login")
def login_form(request: Request):
    return page(request, "auth.html", mode="login")


@app.post("/login")
def login(request: Request, username: str = Form(), password: str = Form()):
    db = connection(); user = db.execute("SELECT * FROM users WHERE username=?", (username.strip(),)).fetchone(); db.close()
    if not user or not verify_password(password, user["password_hash"]):
        return page(request, "auth.html", mode="login", error="用户名或密码不正确。")
    request.session.clear()
    request.session["user_id"] = user["id"]
    request.session["csrf_token"] = secrets.token_urlsafe(32)
    return redirect("/")


@app.post("/logout")
def logout(request: Request):
    require_user(request)
    request.session.clear()
    return redirect("/")


@app.get("/logs")
def logs_form(request: Request):
    require_user(request)
    return page(request, "logs.html", results=[])


@app.post("/logs/analyze")
def analyze_logs(request: Request, bundles: list[UploadFile] = File(...)):
    user = require_user(request)
    selected = [bundle for bundle in bundles if bundle.filename]
    if not selected:
        return page(request, "logs.html", results=[], error="请选择至少一个日志文件。")
    db = connection(); results = []
    for bundle in selected:
        stored, original_name = save_upload(bundle, "logs")
        results.append(create_analysis(db, user["id"], stored, original_name))
    db.commit(); db.close()
    return page(request, "logs.html", results=results, severity_label=severity_label)


@app.get("/reports")
def reports(request: Request):
    require_user(request)
    db = connection()
    items = db.execute("SELECT a.*,u.username FROM analyses a JOIN users u ON u.id=a.created_by ORDER BY a.created_at DESC").fetchall()
    db.close()
    return page(request, "reports.html", reports=items)


@app.get("/cases")
def list_knowledge_cases(request: Request, q: str = ""):
    require_user(request)
    value = "%" + q.strip() + "%"
    db = connection()
    items = db.execute(
        """SELECT k.*,u.username,COUNT(DISTINCT l.analysis_id) report_count,COUNT(DISTINCT f.case_id) feature_count,COUNT(DISTINCT i.id) import_count
        FROM knowledge_cases k JOIN users u ON u.id=k.created_by
        LEFT JOIN case_log_links l ON l.knowledge_case_id=k.id
        LEFT JOIN feature_case_links f ON f.knowledge_case_id=k.id
        LEFT JOIN case_imports i ON i.knowledge_case_id=k.id
        WHERE k.title LIKE ? OR k.summary LIKE ? OR k.body LIKE ?
        GROUP BY k.id ORDER BY k.updated_at DESC""", (value, value, value)
    ).fetchall()
    db.close()
    return page(request, "knowledge_cases.html", knowledge_cases=items, q=q)


@app.get("/cases/new")
def new_knowledge_case(request: Request):
    require_user(request)
    return page(request, "knowledge_case_form.html", knowledge_case=None, imported_document=None)


def draft_case_import(db, import_id: Optional[int], user_id: int):
    if not import_id:
        return None
    return db.execute(
        """SELECT * FROM case_imports
        WHERE id=? AND imported_by=? AND knowledge_case_id IS NULL""",
        (import_id, user_id),
    ).fetchone()


def draft_case_imports(db, user_id: int):
    return db.execute(
        """SELECT * FROM case_imports
        WHERE imported_by=? AND knowledge_case_id IS NULL ORDER BY created_at DESC""",
        (user_id,),
    ).fetchall()


def case_import_page(request: Request, user, **context):
    db = connection(); drafts = draft_case_imports(db, user["id"]); db.close()
    return page(request, "knowledge_case_import.html", supported_formats="DOCX、PPTX、Markdown、TXT、DOC、PPT", draft_imports=drafts, **context)


@app.get("/cases/import")
def import_knowledge_case_form(request: Request):
    user = require_user(request)
    return case_import_page(request, user)


@app.post("/cases/import")
def import_knowledge_case_source(request: Request, document: UploadFile = File()):
    user = require_user(request)
    original_name = Path(document.filename or "").name
    if not original_name:
        return case_import_page(request, user, error="请选择一份案例资料后再导入。")
    if Path(original_name).suffix.lower() not in SUPPORTED_SUFFIXES:
        return case_import_page(request, user, error="暂不支持该资料格式。请上传 DOCX、PPTX、Markdown、TXT、DOC 或 PPT。")
    stored = None
    try:
        stored, safe_name = save_upload(document, "case-imports")
        body, source_format, extraction_note = extract_case_document(stored, safe_name)
    except (CaseImportError, HTTPException) as error:
        if stored:
            stored.unlink(missing_ok=True)
        message = error.detail if isinstance(error, HTTPException) else str(error)
        return case_import_page(request, user, error=message)
    db = connection()
    import_id = db.execute(
        """INSERT INTO case_imports (original_name,storage_path,source_format,extracted_characters,extraction_note,extracted_body,imported_by)
        VALUES (?,?,?,?,?,?,?)""",
        (safe_name, str(stored), source_format, len(body), extraction_note, body, user["id"]),
    ).lastrowid
    imported_document = db.execute("SELECT * FROM case_imports WHERE id=?", (import_id,)).fetchone()
    db.commit(); db.close()
    return page(
        request,
        "knowledge_case_form.html",
        knowledge_case={"title": suggested_title(safe_name, body), "summary": suggested_summary(body), "body": body},
        imported_document=imported_document,
        notice="资料已导入为待发布草稿。请校对内容后再发布。",
    )


@app.get("/cases/imports/{import_id}/edit")
def resume_case_import(request: Request, import_id: int):
    user = require_user(request)
    db = connection(); imported_document = draft_case_import(db, import_id, user["id"]); db.close()
    if not imported_document:
        raise HTTPException(404)
    body = imported_document["extracted_body"]
    return page(
        request,
        "knowledge_case_form.html",
        knowledge_case={"title": suggested_title(imported_document["original_name"], body), "summary": suggested_summary(body), "body": body},
        imported_document=imported_document,
        notice="已恢复待发布草稿。请继续校对后发布。",
    )


def auto_link_knowledge_case_features(db, knowledge_case_id: int, user_id: int, article_text: str, analysis_ids: list[int]):
    feature_ids = {
        row["case_id"]
        for analysis_id in analysis_ids
        for row in db.execute(
            """SELECT m.case_id FROM analysis_matches m JOIN cases c ON c.id=m.case_id
            WHERE m.analysis_id=? AND m.feature_version=c.rule_version""",
            (analysis_id,),
        ).fetchall()
    }
    searchable = article_text.lower()
    for feature in db.execute("SELECT id,title,keywords FROM cases").fetchall():
        terms = [feature["title"]] + [value.strip() for value in feature["keywords"].replace("，", ",").replace(";", ",").split(",")]
        if any(len(term) >= 2 and term.lower() in searchable for term in terms):
            feature_ids.add(feature["id"])
    for feature_id in feature_ids:
        db.execute("INSERT OR IGNORE INTO feature_case_links (case_id,knowledge_case_id,linked_by) VALUES (?,?,?)", (feature_id, knowledge_case_id, user_id))


@app.post("/cases")
def create_knowledge_case(request: Request, title: str = Form(), summary: str = Form(""), body: str = Form(""), import_id: Optional[int] = Form(None), bundles: list[UploadFile] = File([])):
    user = require_user(request)
    selected = [bundle for bundle in bundles if bundle.filename]
    if not title.strip() or (not body.strip() and not selected):
        db = connection(); imported_document = draft_case_import(db, import_id, user["id"]); db.close()
        return page(request, "knowledge_case_form.html", knowledge_case={"title": title, "summary": summary, "body": body}, imported_document=imported_document, error="请填写案例标题，并至少提供案例正文或一份日志。")
    db = connection()
    imported_document = draft_case_import(db, import_id, user["id"])
    if import_id and not imported_document:
        db.close()
        return page(request, "knowledge_case_form.html", knowledge_case={"title": title, "summary": summary, "body": body}, imported_document=None, error="导入草稿不存在、已发布，或不属于当前账号。请重新导入资料。")
    knowledge_case_id = db.execute(
        "INSERT INTO knowledge_cases (title,summary,body,created_by) VALUES (?,?,?,?)",
        (title.strip(), summary.strip(), body.strip(), user["id"]),
    ).lastrowid
    if imported_document:
        db.execute("UPDATE case_imports SET knowledge_case_id=?,extracted_body='' WHERE id=?", (knowledge_case_id, imported_document["id"]))
    analysis_ids = []
    for bundle in selected:
        stored, original_name = save_upload(bundle, "logs")
        report = create_analysis(db, user["id"], stored, original_name)
        db.execute("INSERT OR IGNORE INTO case_log_links (knowledge_case_id,analysis_id,linked_by) VALUES (?,?,?)", (knowledge_case_id, report["id"], user["id"]))
        analysis_ids.append(report["id"])
    auto_link_knowledge_case_features(db, knowledge_case_id, user["id"], " ".join((title, summary, body)), analysis_ids)
    db.commit(); db.close()
    return redirect(f"/cases/{knowledge_case_id}")


@app.post("/cases/imports/{import_id}/discard")
def discard_case_import(request: Request, import_id: int):
    user = require_user(request)
    db = connection()
    imported_document = draft_case_import(db, import_id, user["id"])
    if not imported_document:
        db.close()
        raise HTTPException(404)
    db.execute("DELETE FROM case_imports WHERE id=?", (import_id,))
    db.commit(); db.close()
    Path(imported_document["storage_path"]).unlink(missing_ok=True)
    return redirect("/cases/new")


@app.get("/cases/imports/{import_id}/download")
def download_case_import(request: Request, import_id: int):
    user = require_user(request)
    db = connection()
    imported_document = db.execute(
        """SELECT i.*,k.created_by AS case_created_by
        FROM case_imports i LEFT JOIN knowledge_cases k ON k.id=i.knowledge_case_id
        WHERE i.id=?""",
        (import_id,),
    ).fetchone()
    db.close()
    if not imported_document:
        raise HTTPException(404)
    if not can_access_case_import_source(user, imported_document):
        raise HTTPException(403, "仅导入人、案例作者或审核人员可下载原始资料")
    stored = Path(imported_document["storage_path"])
    if not stored.is_file():
        raise HTTPException(404, "原始导入资料已不存在")
    return FileResponse(stored, filename=imported_document["original_name"], media_type="application/octet-stream")


@app.get("/cases/{knowledge_case_id}")
def knowledge_case_detail(request: Request, knowledge_case_id: int):
    user = require_user(request)
    db = connection()
    knowledge_case = db.execute("SELECT k.*,u.username FROM knowledge_cases k JOIN users u ON u.id=k.created_by WHERE k.id=?", (knowledge_case_id,)).fetchone()
    reports = db.execute("SELECT a.* FROM case_log_links l JOIN analyses a ON a.id=l.analysis_id WHERE l.knowledge_case_id=? ORDER BY l.created_at DESC", (knowledge_case_id,)).fetchall()
    features = db.execute("SELECT c.* FROM feature_case_links l JOIN cases c ON c.id=l.case_id WHERE l.knowledge_case_id=? ORDER BY c.updated_at DESC", (knowledge_case_id,)).fetchall()
    imported_documents = db.execute(
        """SELECT i.*,k.created_by AS case_created_by FROM case_imports i
        JOIN knowledge_cases k ON k.id=i.knowledge_case_id
        WHERE i.knowledge_case_id=? ORDER BY i.created_at DESC""",
        (knowledge_case_id,),
    ).fetchall()
    db.close()
    if not knowledge_case:
        raise HTTPException(404)
    documents = []
    for imported_document in imported_documents:
        item = dict(imported_document)
        item["can_download_source"] = can_access_case_import_source(user, imported_document)
        documents.append(item)
    return page(request, "knowledge_case_detail.html", knowledge_case=knowledge_case, reports=reports, features=features, imported_documents=documents, severity_label=severity_label, case_import_format_label=case_import_format_label)


@app.get("/requests")
def list_requirement_requests(request: Request, status: str = "all", q: str = ""):
    user = require_user(request)
    allowed_statuses = {"pending", "accepted", "planned", "implemented", "declined"}
    status = status if status in allowed_statuses else "all"
    value = "%" + q.strip() + "%"
    where, params = ["(r.title LIKE ? OR r.description LIKE ? OR r.expected_value LIKE ?)"], [value, value, value]
    if status != "all":
        where.append("r.status=?"); params.append(status)
    db = connection()
    items = db.execute(
        """SELECT r.*,u.username,COUNT(e.id) review_count FROM requirement_requests r
        JOIN users u ON u.id=r.created_by LEFT JOIN requirement_review_events e ON e.requirement_id=r.id
        WHERE """ + " AND ".join(where) + " GROUP BY r.id ORDER BY CASE r.status WHEN 'pending' THEN 1 WHEN 'accepted' THEN 2 WHEN 'planned' THEN 3 WHEN 'implemented' THEN 4 ELSE 5 END,r.updated_at DESC",
        params,
    ).fetchall()
    counts = {item["status"]: item["count"] for item in db.execute("SELECT status,COUNT(*) AS count FROM requirement_requests GROUP BY status").fetchall()}
    db.close()
    return page(request, "requests.html", requirements=items, counts=counts, status=status, q=q, requirement_status_label=requirement_status_label, requirement_category_label=requirement_category_label, cadence=requirement_review_cadence(), can_review=can_review_requirements(user))


@app.get("/requests/new")
def new_requirement_request(request: Request):
    require_user(request)
    return page(request, "request_form.html", cadence=requirement_review_cadence())


@app.post("/requests")
def create_requirement_request(request: Request, title: str = Form(), category: str = Form("feature"), description: str = Form(), expected_value: str = Form("")):
    user = require_user(request)
    allowed_categories = {"feature", "workflow", "ui", "knowledge", "other"}
    if not title.strip() or not description.strip():
        return page(request, "request_form.html", cadence=requirement_review_cadence(), error="请填写需求标题和详细说明。")
    db = connection()
    requirement_id = db.execute(
        "INSERT INTO requirement_requests (title,category,description,expected_value,created_by) VALUES (?,?,?,?,?)",
        (title.strip(), category if category in allowed_categories else "other", description.strip(), expected_value.strip(), user["id"]),
    ).lastrowid
    db.commit(); db.close()
    return redirect(f"/requests/{requirement_id}")


@app.get("/requests/{requirement_id}")
def requirement_request_detail(request: Request, requirement_id: int):
    user = require_user(request); db = connection()
    requirement = db.execute("SELECT r.*,u.username FROM requirement_requests r JOIN users u ON u.id=r.created_by WHERE r.id=?", (requirement_id,)).fetchone()
    events = db.execute("SELECT e.*,u.username FROM requirement_review_events e JOIN users u ON u.id=e.reviewed_by WHERE e.requirement_id=? ORDER BY e.reviewed_at DESC", (requirement_id,)).fetchall()
    db.close()
    if not requirement:
        raise HTTPException(404)
    return page(request, "request_detail.html", requirement=requirement, events=events, requirement_status_label=requirement_status_label, requirement_category_label=requirement_category_label, cadence=requirement_review_cadence(), can_review=can_review_requirements(user))


@app.post("/requests/{requirement_id}/review")
def review_requirement_request(request: Request, requirement_id: int, status: str = Form(), note: str = Form("")):
    user = require_user(request)
    if not can_review_requirements(user):
        raise HTTPException(403, "当前账号未配置为需求评审人")
    allowed_statuses = {"accepted", "planned", "implemented", "declined"}
    if status not in allowed_statuses:
        raise HTTPException(400, "无效的需求状态")
    db = connection()
    requirement = db.execute("SELECT id FROM requirement_requests WHERE id=?", (requirement_id,)).fetchone()
    if not requirement:
        db.close(); raise HTTPException(404)
    db.execute("UPDATE requirement_requests SET status=?,updated_at=CURRENT_TIMESTAMP WHERE id=?", (status, requirement_id))
    db.execute("INSERT INTO requirement_review_events (requirement_id,status,note,reviewed_by) VALUES (?,?,?,?)", (requirement_id, status, note.strip(), user["id"]))
    db.commit(); db.close()
    return redirect(f"/requests/{requirement_id}")


def report_context(db, analysis_id: int):
    report = db.execute("SELECT a.*,u.username FROM analyses a JOIN users u ON u.id=a.created_by WHERE a.id=?", (analysis_id,)).fetchone()
    if not report:
        return None, [], [], []
    rows = db.execute(
        """SELECT c.*,m.evidence,m.feature_version,l.relation_type FROM feature_log_links l JOIN cases c ON c.id=l.case_id
        LEFT JOIN analysis_matches m ON m.analysis_id=l.analysis_id AND m.case_id=l.case_id AND m.feature_version=c.rule_version
        WHERE l.analysis_id=? ORDER BY CASE c.severity WHEN 'critical' THEN 1 WHEN 'high' THEN 2 WHEN 'medium' THEN 3 ELSE 4 END""", (analysis_id,)
    ).fetchall()
    all_features = db.execute("SELECT id,title,severity FROM cases ORDER BY title").fetchall()
    skill_rows = db.execute(
        "SELECT * FROM analysis_skill_findings WHERE analysis_id=? ORDER BY CASE severity WHEN 'critical' THEN 1 WHEN 'high' THEN 2 WHEN 'medium' THEN 3 ELSE 4 END,id",
        (analysis_id,),
    ).fetchall()
    skill_findings = []
    for row in skill_rows:
        item = dict(row)
        try:
            item["evidence_items"] = json.loads(item.pop("evidence") or "[]")
        except (TypeError, ValueError):
            item["evidence_items"] = []
        try:
            item["metadata_items"] = json.loads(item.pop("metadata") or "{}")
        except (TypeError, ValueError):
            item["metadata_items"] = {}
        skill_findings.append(item)
    return report, rows, all_features, skill_findings


@app.get("/reports/{analysis_id}")
def report_detail(request: Request, analysis_id: int):
    user = require_user(request); db = connection(); report, features, available, skill_findings = report_context(db, analysis_id); db.close()
    if not report: raise HTTPException(404)
    try:
        analysis_summary = json.loads(report["summary"] or "{}")
    except (TypeError, ValueError):
        analysis_summary = {}
    can_access_source = can_access_report_source(user, report)
    return page(request, "report_detail.html", report=report, features=decoded_report_features(features), available_features=available, skill_findings=skill_findings, analysis_summary=analysis_summary, severity_label=severity_label, can_link_features=can_access_source, can_download_original=can_access_source)


def decoded_report_features(features):
    decoded = []
    for feature in features:
        item = dict(feature)
        try:
            item["evidence_items"] = json.loads(feature["evidence"] or "[]")
        except (TypeError, ValueError):
            item["evidence_items"] = []
        decoded.append(item)
    return decoded


@app.get("/reports/{analysis_id}/export.html")
def export_analysis_report(request: Request, analysis_id: int):
    require_user(request); db = connection(); report, features, _, skill_findings = report_context(db, analysis_id); db.close()
    if not report:
        raise HTTPException(404)
    try:
        summary = json.loads(report["summary"] or "{}")
    except (TypeError, ValueError):
        summary = {}
    rendered = templates.get_template("report_export.html").render(
        report=report,
        summary=summary,
        features=decoded_report_features(features),
        skill_findings=skill_findings,
        severity_label=severity_label,
    )
    return HTMLResponse(
        rendered,
        headers={"Content-Disposition": f'attachment; filename="bmc-analysis-report-{analysis_id}.html"'},
    )


@app.get("/reports/{analysis_id}/download")
def download_original_log(request: Request, analysis_id: int):
    user = require_user(request); db = connection(); report = db.execute("SELECT original_name,storage_path,created_by FROM analyses WHERE id=?", (analysis_id,)).fetchone(); db.close()
    if not report:
        raise HTTPException(404)
    if not can_access_report_source(user, report):
        raise HTTPException(403, "仅日志上传者、审核者或管理员可下载原始日志")
    stored = Path(report["storage_path"])
    if not stored.is_file():
        raise HTTPException(404, "原始日志文件已不在存储区，请联系管理员从备份恢复。")
    return FileResponse(stored, filename=report["original_name"], media_type="application/octet-stream")


@app.post("/reports/{analysis_id}/features")
def link_feature(request: Request, analysis_id: int, case_id: int = Form()):
    user = require_user(request); db = connection()
    report = db.execute("SELECT id,created_by FROM analyses WHERE id=?", (analysis_id,)).fetchone()
    if not report: db.close(); raise HTTPException(404)
    if not can_access_report_source(user, report): db.close(); raise HTTPException(403, "仅日志上传者、审核者或管理员可关联特征")
    if not db.execute("SELECT 1 FROM cases WHERE id=?", (case_id,)).fetchone(): db.close(); raise HTTPException(404, "特征不存在")
    db.execute("INSERT OR IGNORE INTO feature_log_links (case_id,analysis_id,relation_type,linked_by) VALUES (?,?,?,?)", (case_id, analysis_id, "manual", user["id"]))
    db.commit(); db.close()
    return redirect(f"/reports/{analysis_id}")


def report_prompt(report, features, skill_findings):
    return {
        "report": {"file": report["original_name"], "status": report["status"], "files_read": report["file_count"], "matched_features": report["match_count"]},
        "features": [{"name": row["title"], "severity": row["severity"], "description": row["symptom"], "suggestion": row["solution"]} for row in features],
        "bmc_skill_findings": [{"name": row["title"], "severity": row["severity"], "summary": row["summary"], "diagnosis": row["diagnosis"], "solution": row["solution"], "evidence": row["evidence_items"]} for row in skill_findings],
    }


def llm_stream(prompt: str, fallback: str) -> Iterator[str]:
    key = os.getenv("LLM_API_KEY")
    if not key:
        yield "未配置 LLM API Key，当前展示基于本地特征库的建议：\n\n"
        yield fallback
        return
    body = json.dumps({"model": os.getenv("LLM_MODEL", "gpt-4.1-mini"), "stream": True, "temperature": 0.2, "messages": [{"role": "system", "content": "你是服务器硬件维护专家。使用中文，以 Markdown 输出；使用二级或三级标题、项目符号和加粗重点，按风险、证据、排查步骤、处置建议的结构回答；不要编造未提供的日志事实。"}, {"role": "user", "content": prompt}]}, ensure_ascii=False).encode()
    request = urllib.request.Request(os.getenv("LLM_BASE_URL", "https://api.openai.com/v1").rstrip("/") + "/chat/completions", data=body, headers={"Authorization": "Bearer " + key, "Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(request, timeout=60) as response:
            for raw in response:
                line = raw.decode("utf-8", errors="replace").strip()
                if not line.startswith("data:"): continue
                payload = line[5:].strip()
                if payload == "[DONE]": break
                try:
                    delta = json.loads(payload)["choices"][0].get("delta", {}).get("content", "")
                    if delta: yield delta
                except (KeyError, IndexError, json.JSONDecodeError):
                    continue
    except (urllib.error.URLError, TimeoutError) as error:
        yield f"模型服务暂不可用：{error}"


@app.get("/reports/{analysis_id}/llm/stream")
def analyze_report_with_llm(request: Request, analysis_id: int):
    require_user(request); db = connection(); report, features, _, skill_findings = report_context(db, analysis_id); db.close()
    if not report: raise HTTPException(404)
    prompt = "请分析下面这一份 BMC 日志报告：\n" + json.dumps(report_prompt(report, features, skill_findings), ensure_ascii=False, indent=2)
    fallback_parts = [f"### 【{severity_label(finding['severity'])}】{finding['title']}（BMC Skill）\n\n- **结论**：{finding['summary'] or finding['diagnosis'] or '已由内网 Skill 识别'}\n- **诊断**：{finding['diagnosis'] or '请核对下方证据'}\n- **建议**：{finding['solution'] or '请按公司维护流程处置'}" for finding in skill_findings]
    fallback_parts += [f"### 【{severity_label(feature['severity'])}】{feature['title']}（特征库）\n\n- **判断**：{feature['diagnosis']}\n- **建议**：{feature['solution']}" for feature in features]
    fallback = "## 报告概览\n\n- **日志包**：" + report["original_name"] + "\n- **读取文件**：" + str(report["file_count"]) + "\n\n" + ("\n\n".join(fallback_parts) if fallback_parts else "### 建议\n\n未识别到明确问题。建议先检查 SEL / 事件日志中的错误码，再补充公司 Skill 或特征库规则。")
    return StreamingResponse(llm_stream(prompt, fallback), media_type="text/plain; charset=utf-8", headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})


@app.get("/features")
def list_features(request: Request, q: str = ""):
    require_user(request)
    db = connection(); value = "%" + q.strip() + "%"
    features = db.execute(
        """SELECT c.*,u.username,COUNT(DISTINCT cc.id) condition_count,COUNT(DISTINCT l.analysis_id) report_count FROM cases c
        JOIN users u ON u.id=c.created_by LEFT JOIN case_conditions cc ON cc.case_id=c.id LEFT JOIN feature_log_links l ON l.case_id=c.id
        WHERE c.title LIKE ? OR c.keywords LIKE ? OR c.tags LIKE ? OR c.symptom LIKE ?
        GROUP BY c.id ORDER BY CASE c.severity WHEN 'critical' THEN 1 WHEN 'high' THEN 2 WHEN 'medium' THEN 3 ELSE 4 END,c.updated_at DESC""", (value, value, value, value)
    ).fetchall(); db.close()
    return page(request, "features.html", features=features, q=q, severity_label=severity_label)


@app.get("/features/new")
def new_feature(request: Request):
    require_user(request)
    db = connection(); knowledge_cases = db.execute("SELECT id,title FROM knowledge_cases ORDER BY updated_at DESC LIMIT 100").fetchall(); db.close()
    return page(request, "feature_form.html", feature=None, conditions=[], knowledge_cases=knowledge_cases, linked_case_ids=[])


def validate_feature(title, description, diagnosis, solution, patterns, expressions, flags):
    conditions = [(pattern.strip(), expression.strip(), str(index) in flags) for index, (pattern, expression) in enumerate(zip(patterns, expressions)) if pattern.strip() and expression.strip()]
    if not all([title.strip(), description.strip(), diagnosis.strip(), solution.strip(), conditions]):
        return None
    return conditions


def snapshot_feature_version(db, feature_id: int, version: int, user_id: int):
    feature = db.execute("SELECT * FROM cases WHERE id=?", (feature_id,)).fetchone()
    conditions = [
        dict(item)
        for item in db.execute(
            "SELECT file_pattern,expression,is_regex FROM case_conditions WHERE case_id=? ORDER BY id", (feature_id,)
        ).fetchall()
    ]
    db.execute(
        """INSERT INTO feature_versions
        (case_id,version,title,symptom,diagnosis,solution,keywords,tags,severity,match_mode,conditions,created_by)
        VALUES (?,?,?,?,?,?,?,?,?,?,?,?)""",
        (
            feature_id, version, feature["title"], feature["symptom"], feature["diagnosis"],
            feature["solution"], feature["keywords"], feature["tags"], feature["severity"],
            feature["match_mode"], json.dumps(conditions, ensure_ascii=False), user_id,
        ),
    )


def active_match_count(db, analysis_id: int) -> int:
    return db.execute(
        """SELECT COUNT(*) FROM analysis_matches m JOIN cases c ON c.id=m.case_id
        WHERE m.analysis_id=? AND m.feature_version=c.rule_version""",
        (analysis_id,),
    ).fetchone()[0]


def update_analysis_match_summary(db, analysis_id: int):
    analysis = db.execute("SELECT summary,file_count FROM analyses WHERE id=?", (analysis_id,)).fetchone()
    if not analysis:
        return
    try:
        summary = json.loads(analysis["summary"] or "{}")
    except (TypeError, ValueError):
        summary = {}
    summary["file_count"] = analysis["file_count"]
    summary["match_count"] = active_match_count(db, analysis_id)
    db.execute(
        "UPDATE analyses SET match_count=?,summary=? WHERE id=?",
        (summary["match_count"], json.dumps(summary, ensure_ascii=False), analysis_id),
    )


def refresh_feature_matches(db, feature_id: int, user_id: int):
    """Re-evaluate all completed reports against the feature's current rule version.

    Old `analysis_matches` rows are intentionally retained.  The active report
    view only joins the version equal to `cases.rule_version`, so historical
    evidence remains auditable while current counters stay correct.
    """
    feature = db.execute("SELECT * FROM cases WHERE id=?", (feature_id,)).fetchone()
    if not feature:
        raise HTTPException(404)
    conditions = db.execute("SELECT * FROM case_conditions WHERE case_id=? ORDER BY id", (feature_id,)).fetchall()
    reports = db.execute(
        "SELECT id,original_name,storage_path FROM analyses WHERE status='completed' ORDER BY id"
    ).fetchall()
    db.execute("DELETE FROM feature_log_links WHERE case_id=? AND relation_type='automatic'", (feature_id,))

    matched, failures = 0, []
    for report in reports:
        try:
            stored = Path(report["storage_path"])
            if not stored.is_file():
                raise FileNotFoundError
            condition_evidence, is_hit = evaluate_feature_conditions(
                read_log_bundle(stored), conditions, feature["match_mode"]
            )
            if is_hit:
                db.execute(
                    """INSERT OR REPLACE INTO analysis_matches
                    (analysis_id,case_id,feature_version,evidence) VALUES (?,?,?,?)""",
                    (report["id"], feature_id, feature["rule_version"], json.dumps(condition_evidence, ensure_ascii=False)),
                )
                db.execute(
                    "INSERT OR IGNORE INTO feature_log_links (case_id,analysis_id,relation_type,linked_by) VALUES (?,?,?,?)",
                    (feature_id, report["id"], "automatic", user_id),
                )
                matched += 1
        except Exception:
            failures.append(report["original_name"])
        finally:
            update_analysis_match_summary(db, report["id"])
    return {"rechecked": len(reports), "matched": matched, "failed": failures}


def save_feature(db, feature_id, title, description, diagnosis, solution, keywords, tags, severity, match_mode, conditions, user_id, linked_case_ids):
    if feature_id:
        current = db.execute("SELECT rule_version FROM cases WHERE id=?", (feature_id,)).fetchone()
        if not current:
            raise HTTPException(404)
        rule_version = current["rule_version"] + 1
        db.execute("UPDATE cases SET title=?,symptom=?,diagnosis=?,solution=?,keywords=?,tags=?,severity=?,match_mode=?,rule_version=?,updated_at=CURRENT_TIMESTAMP WHERE id=?", (title.strip(), description.strip(), diagnosis.strip(), solution.strip(), keywords.strip(), tags.strip(), severity, match_mode, rule_version, feature_id))
        db.execute("DELETE FROM case_conditions WHERE case_id=?", (feature_id,))
    else:
        rule_version = 1
        feature_id = db.execute("INSERT INTO cases (title,symptom,diagnosis,solution,keywords,tags,severity,match_mode,rule_version,created_by) VALUES (?,?,?,?,?,?,?,?,?,?)", (title.strip(), description.strip(), diagnosis.strip(), solution.strip(), keywords.strip(), tags.strip(), severity, match_mode, rule_version, user_id)).lastrowid
    for pattern, expression, is_regex in conditions:
        db.execute("INSERT INTO case_conditions (case_id,file_pattern,expression,is_regex) VALUES (?,?,?,?)", (feature_id, pattern, expression, is_regex))
    db.execute("DELETE FROM feature_case_links WHERE case_id=?", (feature_id,))
    for knowledge_case_id in {int(value) for value in linked_case_ids if str(value).isdigit()}:
        db.execute(
            """INSERT OR IGNORE INTO feature_case_links (case_id,knowledge_case_id,linked_by)
            SELECT ?,?,? WHERE EXISTS (SELECT 1 FROM knowledge_cases WHERE id=?)""",
            (feature_id, knowledge_case_id, user_id, knowledge_case_id),
        )
    snapshot_feature_version(db, feature_id, rule_version, user_id)
    return feature_id, rule_version


def attach_feature_source_logs(db, feature_id: int, user_id: int, uploads: list[UploadFile]):
    analysis_ids = []
    for upload in (item for item in uploads if item.filename):
        stored, original_name = save_upload(upload, "logs")
        report = create_analysis(db, user_id, stored, original_name)
        analysis_ids.append(report["id"])
        db.execute(
            "INSERT OR IGNORE INTO feature_log_reviews (case_id,analysis_id,status,requested_by) VALUES (?,?,?,?)",
            (feature_id, report["id"], "pending", user_id),
        )
    return analysis_ids


@app.post("/features")
def create_feature(request: Request, title: str = Form(), description: str = Form(), diagnosis: str = Form(), solution: str = Form(), keywords: str = Form(""), tags: str = Form(""), severity: str = Form("medium"), match_mode: str = Form("all"), file_patterns: list[str] = Form([]), expressions: list[str] = Form([]), regex_flags: list[str] = Form([]), knowledge_case_ids: list[int] = Form([]), source_bundles: list[UploadFile] = File([])):
    user = require_user(request); conditions = validate_feature(title, description, diagnosis, solution, file_patterns, expressions, regex_flags)
    if not conditions:
        db = connection(); knowledge_cases = db.execute("SELECT id,title FROM knowledge_cases ORDER BY updated_at DESC LIMIT 100").fetchall(); db.close()
        return page(request, "feature_form.html", feature=None, conditions=[], knowledge_cases=knowledge_cases, linked_case_ids=knowledge_case_ids, error="请完整填写问题信息，并至少提供一条有效日志条件。")
    db = connection(); feature_id, _ = save_feature(db, None, title, description, diagnosis, solution, keywords, tags, severity if severity in ("critical", "high", "medium", "low") else "medium", "any" if match_mode == "any" else "all", conditions, user["id"], knowledge_case_ids); analysis_ids = attach_feature_source_logs(db, feature_id, user["id"], source_bundles); db.commit(); db.close()
    return redirect(f"/features/{feature_id}/assist" if analysis_ids else f"/features/{feature_id}")


@app.get("/features/{feature_id}")
def feature_detail(request: Request, feature_id: int, rechecked: int = 0, matched: int = 0, failed: int = 0):
    user = require_user(request)
    db = connection()
    feature = db.execute("SELECT c.*,u.username FROM cases c JOIN users u ON u.id=c.created_by WHERE c.id=?", (feature_id,)).fetchone()
    conditions = db.execute("SELECT * FROM case_conditions WHERE case_id=?", (feature_id,)).fetchall()
    reports = db.execute("SELECT a.*,l.relation_type FROM feature_log_links l JOIN analyses a ON a.id=l.analysis_id WHERE l.case_id=? ORDER BY l.created_at DESC", (feature_id,)).fetchall(); db.close()
    db = connection()
    knowledge_cases = db.execute("SELECT k.* FROM feature_case_links l JOIN knowledge_cases k ON k.id=l.knowledge_case_id WHERE l.case_id=? ORDER BY k.updated_at DESC", (feature_id,)).fetchall()
    reviews = db.execute("SELECT r.*,a.original_name,a.status AS analysis_status FROM feature_log_reviews r JOIN analyses a ON a.id=r.analysis_id WHERE r.case_id=? ORDER BY r.updated_at DESC", (feature_id,)).fetchall()
    db.close()
    if not feature: raise HTTPException(404)
    notice = None
    if rechecked:
        notice = f"已按规则版本 v{feature['rule_version']} 重新检查 {rechecked} 份完成报告，当前命中 {matched} 份。"
        if failed:
            notice += f"其中 {failed} 份来源文件无法读取，未改动其历史证据。"
    return page(request, "feature_detail.html", feature=feature, conditions=conditions, reports=reports, knowledge_cases=knowledge_cases, reviews=reviews, severity_label=severity_label, notice=notice, can_manage_feature=can_manage_feature(user, feature), can_review_feature=can_review_features(user, feature))


@app.get("/features/{feature_id}/edit")
def edit_feature_form(request: Request, feature_id: int):
    user = require_user(request); db = connection(); feature = db.execute("SELECT * FROM cases WHERE id=?", (feature_id,)).fetchone(); conditions = db.execute("SELECT * FROM case_conditions WHERE case_id=?", (feature_id,)).fetchall(); knowledge_cases = db.execute("SELECT id,title FROM knowledge_cases ORDER BY updated_at DESC LIMIT 100").fetchall(); linked_case_ids = [item["knowledge_case_id"] for item in db.execute("SELECT knowledge_case_id FROM feature_case_links WHERE case_id=?", (feature_id,)).fetchall()]; db.close()
    if not feature: raise HTTPException(404)
    if not can_manage_feature(user, feature): raise HTTPException(403, "仅创建者或管理员可以编辑特征")
    return page(request, "feature_form.html", feature=feature, conditions=conditions, knowledge_cases=knowledge_cases, linked_case_ids=linked_case_ids)


@app.post("/features/{feature_id}/edit")
def edit_feature(request: Request, feature_id: int, title: str = Form(), description: str = Form(), diagnosis: str = Form(), solution: str = Form(), keywords: str = Form(""), tags: str = Form(""), severity: str = Form("medium"), match_mode: str = Form("all"), file_patterns: list[str] = Form([]), expressions: list[str] = Form([]), regex_flags: list[str] = Form([]), knowledge_case_ids: list[int] = Form([]), source_bundles: list[UploadFile] = File([])):
    user = require_user(request); conditions = validate_feature(title, description, diagnosis, solution, file_patterns, expressions, regex_flags); db = connection(); feature = db.execute("SELECT * FROM cases WHERE id=?", (feature_id,)).fetchone()
    if not feature: db.close(); raise HTTPException(404)
    if not can_manage_feature(user, feature): db.close(); raise HTTPException(403, "仅创建者或管理员可以编辑特征")
    if not conditions:
        knowledge_cases = db.execute("SELECT id,title FROM knowledge_cases ORDER BY updated_at DESC LIMIT 100").fetchall(); db.close()
        return page(request, "feature_form.html", feature=feature, conditions=[], knowledge_cases=knowledge_cases, linked_case_ids=knowledge_case_ids, error="请完整填写问题信息，并至少提供一条有效日志条件。")
    save_feature(db, feature_id, title, description, diagnosis, solution, keywords, tags, severity if severity in ("critical", "high", "medium", "low") else "medium", "any" if match_mode == "any" else "all", conditions, user["id"], knowledge_case_ids)
    refresh = refresh_feature_matches(db, feature_id, user["id"])
    analysis_ids = attach_feature_source_logs(db, feature_id, user["id"], source_bundles)
    db.commit(); db.close()
    if analysis_ids:
        return redirect(f"/features/{feature_id}/assist")
    return redirect(f"/features/{feature_id}?rechecked={refresh['rechecked']}&matched={refresh['matched']}&failed={len(refresh['failed'])}")


@app.post("/features/{feature_id}/recheck")
def recheck_feature(request: Request, feature_id: int):
    user = require_user(request); db = connection()
    feature = db.execute("SELECT created_by FROM cases WHERE id=?", (feature_id,)).fetchone()
    if not feature:
        db.close(); raise HTTPException(404)
    if not can_manage_feature(user, feature):
        db.close(); raise HTTPException(403, "仅创建者或管理员可以重新检查特征")
    refresh = refresh_feature_matches(db, feature_id, user["id"])
    db.commit(); db.close()
    return redirect(f"/features/{feature_id}?rechecked={refresh['rechecked']}&matched={refresh['matched']}&failed={len(refresh['failed'])}")


def review_status_label(status: str) -> str:
    return {"pending": "待人工确认", "confirmed": "已确认为特征证据", "rejected": "不作为特征证据"}.get(status, "待人工确认")


def collect_source_log_evidence(analysis, conditions, match_mode: str):
    """Read bounded, rule-scoped excerpts from the source archive for AI review."""
    try:
        stored = Path(analysis["storage_path"])
        if not stored.is_file():
            raise FileNotFoundError
        files = read_log_bundle(stored)
        evidence_items, is_hit = evaluate_feature_conditions(files, conditions, match_mode)
        return {"files_read": len(files), "matches_current_rule": is_hit, "conditions": evidence_items}
    except Exception:
        return {"files_read": 0, "matches_current_rule": False, "conditions": [], "error": "来源日志当前无法读取，请重新上传后再复核。"}


def feature_review_context(db, feature_id: int):
    feature = db.execute("SELECT * FROM cases WHERE id=?", (feature_id,)).fetchone()
    if not feature:
        return None, [], []
    conditions = db.execute("SELECT file_pattern,expression,is_regex FROM case_conditions WHERE case_id=?", (feature_id,)).fetchall()
    reviews = db.execute(
        """SELECT r.*,a.original_name,a.storage_path,a.status AS analysis_status,a.file_count,a.match_count,m.evidence
        FROM feature_log_reviews r JOIN analyses a ON a.id=r.analysis_id
        LEFT JOIN analysis_matches m ON m.analysis_id=r.analysis_id AND m.case_id=r.case_id AND m.feature_version=?
        WHERE r.case_id=? ORDER BY r.updated_at DESC""", (feature["rule_version"], feature_id)
    ).fetchall()
    decoded_reviews = []
    for review in reviews:
        item = dict(review)
        try:
            item["evidence_items"] = json.loads(item.pop("evidence") or "[]")
        except (TypeError, ValueError):
            item["evidence_items"] = []
        item["source_evidence"] = collect_source_log_evidence(item, conditions, feature["match_mode"])
        decoded_reviews.append(item)
    return feature, conditions, decoded_reviews


@app.get("/features/{feature_id}/assist")
def feature_assist(request: Request, feature_id: int):
    user = require_user(request); db = connection(); feature, conditions, reviews = feature_review_context(db, feature_id); db.close()
    if not feature:
        raise HTTPException(404)
    if not can_review_features(user, feature):
        raise HTTPException(403, "仅特征创建者、审核者或管理员可以复核来源日志")
    return page(request, "feature_assist.html", feature=feature, conditions=conditions, reviews=reviews, review_status_label=review_status_label, can_review_feature=True)


@app.get("/features/{feature_id}/assist/stream")
def feature_assist_stream(request: Request, feature_id: int):
    user = require_user(request); db = connection(); feature, conditions, reviews = feature_review_context(db, feature_id); db.close()
    if not feature:
        raise HTTPException(404)
    if not can_review_features(user, feature):
        raise HTTPException(403, "仅特征创建者、审核者或管理员可以复核来源日志")
    review_payload = [
        {
            "log": item["original_name"], "analysis_status": item["analysis_status"],
            "review_status": item["status"], "local_rule_evidence": item["source_evidence"],
        }
        for item in reviews
    ]
    prompt = "请作为特征规则复核助手，复核下面的特征与来源日志。`local_rule_evidence` 是系统刚从实际日志中按当前规则提取的受限证据；只能依据其中的文件、行号和原文作判断，不能编造未提供的日志内容。必须以 Markdown 输出，逐份日志明确列出：1. 指向特征的文件路径、行号和原文证据；2. 是单个文件还是多个文件共同指向；3. 证据不足时要向维护人员提出具体追问；4. 最后给出‘建议确认’或‘建议驳回’，但不要替代人工决定。\n\n" + json.dumps({"feature": {"name": feature["title"], "severity": feature["severity"], "description": feature["symptom"], "diagnosis": feature["diagnosis"], "rule_version": feature["rule_version"]}, "conditions": [dict(item) for item in conditions], "source_logs": review_payload}, ensure_ascii=False, indent=2)
    sections = ["## AI 特征证据复核", "\n请逐项核对以下候选日志，再选择确认或驳回。"]
    for review in reviews:
        sections.append(f"\n### {review['original_name']}\n\n- **当前状态**：{review_status_label(review['status'])}")
        source_evidence = review["source_evidence"]
        if source_evidence.get("error"):
            sections.append("- **待处理**：来源日志当前无法读取，请重新上传后再复核。")
            continue
        sections.append(f"- **本次读取文件**：{source_evidence['files_read']} 个\n- **当前规则结论**：{'满足' if source_evidence['matches_current_rule'] else '未满足'}")
        for evidence in source_evidence["conditions"]:
            condition = evidence["condition"]
            found = evidence.get("found")
            if found:
                sections.append(f"- **条件命中**：`{condition['file_pattern']}` / `{condition['expression']}`\n  - 证据：`{found['file']}:{found['line']}`\n  - 原文：{found['excerpt']}")
            elif evidence.get("error"):
                sections.append(f"- **规则错误**：`{condition['expression']}`（{evidence['error']}）")
            else:
                sections.append(f"- **条件未命中**：`{condition['file_pattern']}` / `{condition['expression']}`")
        sections.append("- **请确认**：上述文件与语句是否足以证明该特征？如需多文件共同判断，请补充对应文件路径和关键语句。")
    fallback = "\n".join(sections)
    return StreamingResponse(llm_stream(prompt, fallback), media_type="text/plain; charset=utf-8", headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})


@app.post("/features/{feature_id}/reviews/{analysis_id}")
def update_feature_review(request: Request, feature_id: int, analysis_id: int, decision: str = Form(), note: str = Form("")):
    user = require_user(request)
    if decision not in ("confirmed", "rejected"):
        raise HTTPException(400, "无效的复核决定")
    db = connection()
    feature = db.execute("SELECT created_by FROM cases WHERE id=?", (feature_id,)).fetchone()
    if not feature:
        db.close(); raise HTTPException(404)
    if not can_review_features(user, feature):
        db.close(); raise HTTPException(403, "仅特征创建者、审核者或管理员可以确认来源日志")
    review = db.execute("SELECT 1 FROM feature_log_reviews WHERE case_id=? AND analysis_id=?", (feature_id, analysis_id)).fetchone()
    if not review:
        db.close(); raise HTTPException(404)
    db.execute("UPDATE feature_log_reviews SET status=?,note=?,reviewed_by=?,updated_at=CURRENT_TIMESTAMP WHERE case_id=? AND analysis_id=?", (decision, note.strip(), user["id"], feature_id, analysis_id))
    if decision == "confirmed":
        linked = db.execute("SELECT id FROM feature_log_links WHERE case_id=? AND analysis_id=?", (feature_id, analysis_id)).fetchone()
        if linked:
            db.execute("UPDATE feature_log_links SET relation_type='manual',linked_by=? WHERE id=?", (user["id"], linked["id"]))
        else:
            db.execute("INSERT INTO feature_log_links (case_id,analysis_id,relation_type,linked_by) VALUES (?,?,?,?)", (feature_id, analysis_id, "manual", user["id"]))
    db.commit(); db.close()
    return redirect(f"/features/{feature_id}/assist")


@app.post("/features/{feature_id}/delete")
def delete_feature(request: Request, feature_id: int):
    user = require_user(request); db = connection(); feature = db.execute("SELECT created_by FROM cases WHERE id=?", (feature_id,)).fetchone()
    if not feature: db.close(); raise HTTPException(404)
    if not can_manage_feature(user, feature): db.close(); raise HTTPException(403, "仅创建者或管理员可以删除特征")
    db.execute("DELETE FROM cases WHERE id=?", (feature_id,)); db.commit(); db.close()
    return redirect("/features")


def related_knowledge(question: str):
    normalized = question.lower().strip(); terms = [term for term in normalized.replace("，", " ").replace("。", " ").split() if len(term) >= 2]
    terms += [normalized[index:index + 2] for index in range(len(normalized) - 1) if "\u4e00" <= normalized[index] <= "\u9fff"]
    terms = list(dict.fromkeys(terms)); db = connection(); features = db.execute("SELECT id,title,symptom,diagnosis,solution,keywords,severity FROM cases ORDER BY updated_at DESC").fetchall(); knowledge_cases = db.execute("SELECT id,title,summary,body FROM knowledge_cases ORDER BY updated_at DESC").fetchall(); db.close()
    scored_features, scored_cases = [], []
    for item in features:
        text = " ".join(str(item[key]) for key in item.keys()).lower(); score = sum(term in text for term in terms)
        if score: scored_features.append((score, dict(item)))
    for item in knowledge_cases:
        text = " ".join(str(item[key]) for key in item.keys()).lower(); score = sum(term in text for term in terms)
        if score:
            payload = dict(item); payload["body"] = payload["body"][:2400]
            scored_cases.append((score, payload))
    return [item for _, item in sorted(scored_features, key=lambda pair: pair[0], reverse=True)[:5]], [item for _, item in sorted(scored_cases, key=lambda pair: pair[0], reverse=True)[:4]]


@app.get("/ask")
def ask_form(request: Request):
    user = require_user(request)
    db = connection()
    history = db.execute("SELECT role,content,created_at FROM chat_messages WHERE user_id=? ORDER BY id ASC LIMIT 100", (user["id"],)).fetchall()
    db.close()
    return page(request, "ask.html", history=history)


@app.get("/ask/stream")
def ask_stream(request: Request, question: str = ""):
    user = require_user(request)
    if not question.strip(): raise HTTPException(400, "请输入问题")
    features, knowledge_cases = related_knowledge(question)
    prompt = "用户问题：" + question + "\n\n相关内部知识（特征规则与维护案例）：\n" + json.dumps({"features": features, "knowledge_cases": knowledge_cases}, ensure_ascii=False, indent=2)
    fallback_parts = [f"### 【{severity_label(item['severity'])}】{item['title']}\n\n- **判断**：{item['diagnosis']}\n- **建议**：{item['solution']}" for item in features]
    fallback_parts += [f"### 案例：{item['title']}\n\n{item['summary'] or item['body'][:800]}" for item in knowledge_cases]
    fallback = "\n\n".join(fallback_parts) if fallback_parts else "## 检索结果\n\n未找到直接匹配的内部特征或案例。请补充错误码、部件名称或日志关键字后再试。"
    db = connection()
    db.execute("INSERT INTO chat_messages (user_id,role,content) VALUES (?,?,?)", (user["id"], "user", question.strip()))
    db.commit(); db.close()

    def record_response():
        chunks = []
        for chunk in llm_stream(prompt, fallback):
            chunks.append(chunk)
            yield chunk
        db = connection()
        db.execute("INSERT INTO chat_messages (user_id,role,content) VALUES (?,?,?)", (user["id"], "assistant", "".join(chunks)))
        db.commit(); db.close()

    return StreamingResponse(record_response(), media_type="text/plain; charset=utf-8", headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})


# Existing internal tool distribution routes remain available.
@app.get("/tools")
def list_tools(request: Request, q: str = ""):
    require_user(request)
    db = connection(); value = "%" + q.strip() + "%"
    tools = db.execute("SELECT t.*,u.username,v.version,v.downloads FROM tools t JOIN users u ON u.id=t.created_by LEFT JOIN tool_versions v ON v.id=(SELECT id FROM tool_versions WHERE tool_id=t.id ORDER BY created_at DESC LIMIT 1) WHERE t.name LIKE ? OR t.short_description LIKE ? GROUP BY t.id ORDER BY t.updated_at DESC", (value, value)).fetchall(); db.close()
    return page(request, "tools.html", tools=tools, q=q)


@app.get("/tools/new")
def new_tool_form(request: Request):
    require_user(request); return page(request, "tool_form.html", tool=None)


@app.post("/tools")
def create_tool(request: Request, name: str = Form(), short_description: str = Form(), details: str = Form(), version: str = Form(), release_notes: str = Form(), package: UploadFile = File(), logo: Optional[UploadFile] = File(None)):
    user = require_user(request)
    if not all([name.strip(), short_description.strip(), details.strip(), version.strip(), package.filename]): return page(request, "tool_form.html", tool=None, error="名称、简介、说明、版本和工具文件均为必填。")
    package_path, package_name = save_upload(package, "tools"); logo_path = None
    if logo and logo.filename: logo_path = str(save_upload(logo, "logos")[0])
    db = connection(); tool_id = db.execute("INSERT INTO tools (name,short_description,details,logo_path,created_by) VALUES (?,?,?,?,?)", (name.strip(), short_description.strip(), details.strip(), logo_path, user["id"])).lastrowid
    db.execute("INSERT INTO tool_versions (tool_id,version,release_notes,file_path,file_name,uploaded_by) VALUES (?,?,?,?,?,?)", (tool_id, version.strip(), release_notes.strip(), str(package_path), package_name, user["id"])); db.commit(); db.close()
    return redirect(f"/tools/{tool_id}")


def get_tool(db, tool_id): return db.execute("SELECT t.*,u.username FROM tools t JOIN users u ON u.id=t.created_by WHERE t.id=?", (tool_id,)).fetchone()


@app.get("/tools/{tool_id}")
def tool_detail(request: Request, tool_id: int):
    require_user(request)
    db = connection(); tool = get_tool(db, tool_id)
    if not tool: db.close(); raise HTTPException(404)
    versions = db.execute("SELECT v.*,u.username FROM tool_versions v JOIN users u ON u.id=v.uploaded_by WHERE tool_id=? ORDER BY created_at DESC", (tool_id,)).fetchall(); feedback = db.execute("SELECT f.*,u.username FROM feedback f JOIN users u ON u.id=f.created_by WHERE tool_id=? ORDER BY f.created_at DESC", (tool_id,)).fetchall(); db.close()
    return page(request, "tool_detail.html", tool=tool, versions=versions, feedback=feedback)


@app.get("/tools/{tool_id}/edit")
def edit_tool_form(request: Request, tool_id: int):
    user = require_user(request); db = connection(); tool = get_tool(db, tool_id); db.close()
    if not tool: raise HTTPException(404)
    if tool["created_by"] != user["id"]: raise HTTPException(403, "仅工具作者可以修改介绍")
    return page(request, "tool_edit.html", tool=tool)


@app.post("/tools/{tool_id}/edit")
def edit_tool(request: Request, tool_id: int, name: str = Form(), short_description: str = Form(), details: str = Form(), logo: Optional[UploadFile] = File(None)):
    user = require_user(request); db = connection(); tool = get_tool(db, tool_id)
    if not tool: db.close(); raise HTTPException(404)
    if tool["created_by"] != user["id"]: db.close(); raise HTTPException(403, "仅工具作者可以修改介绍")
    logo_path = tool["logo_path"]
    if logo and logo.filename: logo_path = str(save_upload(logo, "logos")[0])
    db.execute("UPDATE tools SET name=?,short_description=?,details=?,logo_path=?,updated_at=CURRENT_TIMESTAMP WHERE id=?", (name.strip(), short_description.strip(), details.strip(), logo_path, tool_id)); db.commit(); db.close()
    return redirect(f"/tools/{tool_id}")


@app.post("/tools/{tool_id}/versions")
def add_version(request: Request, tool_id: int, version: str = Form(), release_notes: str = Form(""), package: UploadFile = File()):
    user = require_user(request); db = connection(); tool = get_tool(db, tool_id)
    if not tool: db.close(); raise HTTPException(404)
    if tool["created_by"] != user["id"]: db.close(); raise HTTPException(403, "仅工具作者可以发布新版本")
    file_path, file_name = save_upload(package, "tools")
    try:
        db.execute("INSERT INTO tool_versions (tool_id,version,release_notes,file_path,file_name,uploaded_by) VALUES (?,?,?,?,?,?)", (tool_id, version.strip(), release_notes.strip(), str(file_path), file_name, user["id"])); db.execute("UPDATE tools SET updated_at=CURRENT_TIMESTAMP WHERE id=?", (tool_id,)); db.commit()
    except Exception:
        file_path.unlink(missing_ok=True); db.close(); raise HTTPException(400, "版本号不能为空且不可重复")
    db.close(); return redirect(f"/tools/{tool_id}")


@app.post("/tools/{tool_id}/feedback")
def add_feedback(request: Request, tool_id: int, body: str = Form()):
    user = require_user(request)
    if not body.strip(): raise HTTPException(400, "建议不可为空")
    db = connection(); db.execute("INSERT INTO feedback (tool_id,body,created_by) VALUES (?,?,?)", (tool_id, body.strip(), user["id"])); db.commit(); db.close(); return redirect(f"/tools/{tool_id}#feedback")


@app.get("/download/{version_id}")
def download_tool(request: Request, version_id: int):
    user = require_user(request); db = connection(); version = db.execute("SELECT * FROM tool_versions WHERE id=?", (version_id,)).fetchone()
    if not version: db.close(); raise HTTPException(404)
    db.execute("UPDATE tool_versions SET downloads=downloads+1 WHERE id=?", (version_id,)); db.execute("INSERT INTO downloads (tool_version_id,user_id) VALUES (?,?)", (version_id, user["id"])); db.commit(); db.close()
    if not Path(version["file_path"]).exists(): raise HTTPException(404, "文件不存在，请联系上传者")
    return FileResponse(version["file_path"], filename=version["file_name"])


@app.get("/asset/{name}")
def asset(request: Request, name: str):
    require_user(request)
    if Path(name).name != name: raise HTTPException(404)
    candidates = list((UPLOAD_DIR / "logos").glob(name))
    if not candidates: raise HTTPException(404)
    return FileResponse(candidates[0])
