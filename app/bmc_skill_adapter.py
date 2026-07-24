"""Optional adapter for company-internal BMC log parsing skills.

The built-in feature library remains the deterministic baseline.  When an
internal parser becomes available, configure `BMC_SKILL_ADAPTER` with a trusted
Python callable in `module:function` form.  Its normalized findings are stored
next to feature matches and included in the HTML report.
"""

import importlib
import json
import os
from pathlib import Path
from typing import Any


VALID_SEVERITIES = {"critical", "high", "medium", "low"}
MAX_FINDINGS = 100
MAX_EVIDENCE_PER_FINDING = 30
MAX_EXCERPT_CHARS = 1_200


def _json_value(value: Any, fallback: Any) -> Any:
    try:
        json.dumps(value, ensure_ascii=False)
        return value
    except (TypeError, ValueError):
        return fallback


def _normalize_evidence(raw_items: Any) -> list[dict[str, Any]]:
    if not isinstance(raw_items, list):
        return []
    evidence = []
    for item in raw_items[:MAX_EVIDENCE_PER_FINDING]:
        if not isinstance(item, dict) or not item.get("file"):
            continue
        try:
            line = max(1, int(item.get("line", 1)))
        except (TypeError, ValueError):
            line = 1
        evidence.append(
            {
                "file": str(item["file"])[:500],
                "line": line,
                "excerpt": str(item.get("excerpt", ""))[:MAX_EXCERPT_CHARS],
            }
        )
    return evidence


def _normalize_finding(raw: Any, index: int) -> dict[str, Any] | None:
    if not isinstance(raw, dict):
        return None
    rule_id = str(raw.get("rule_id") or raw.get("id") or f"finding-{index}").strip()[:180]
    title = str(raw.get("title") or raw.get("name") or rule_id).strip()[:300]
    if not rule_id or not title:
        return None
    severity = str(raw.get("severity", "medium")).lower().strip()
    return {
        "rule_id": rule_id,
        "title": title,
        "severity": severity if severity in VALID_SEVERITIES else "medium",
        "summary": str(raw.get("summary") or raw.get("description") or "").strip()[:4_000],
        "diagnosis": str(raw.get("diagnosis") or "").strip()[:4_000],
        "solution": str(raw.get("solution") or raw.get("recommendation") or "").strip()[:4_000],
        "evidence": _normalize_evidence(raw.get("evidence", [])),
        "metadata": _json_value(raw.get("metadata", {}), {"note": "metadata is not JSON serializable"}),
    }


def run_bmc_skill(files: dict[str, str], archive_path: Path) -> dict[str, Any]:
    """Run a configured internal adapter without making it a required dependency.

    Adapter contract::

        def analyze_log_bundle(*, files: dict[str, str], archive_path: Path) -> dict:
            return {"skill_name": "...", "skill_version": "...", "findings": [{...}]}

    A missing or failed adapter never stops the core feature analysis.  The
    caller receives a human-readable warning for the report instead.
    """
    target = os.getenv("BMC_SKILL_ADAPTER", "").strip()
    if not target:
        return {"enabled": False, "skill_name": "", "skill_version": "", "findings": [], "warning": ""}
    module_name, separator, function_name = target.partition(":")
    if not module_name or not separator or not function_name:
        return {
            "enabled": True,
            "skill_name": "configured-bmc-skill",
            "skill_version": "",
            "findings": [],
            "warning": "BMC Skill 配置格式无效，应为 module:function。",
        }
    try:
        handler = getattr(importlib.import_module(module_name), function_name)
        payload = handler(files=files, archive_path=archive_path)
    except Exception:
        return {
            "enabled": True,
            "skill_name": module_name,
            "skill_version": "",
            "findings": [],
            "warning": "BMC Skill 未能完成本次解析；基础特征比对已正常完成。",
        }

    if isinstance(payload, list):
        payload = {"findings": payload}
    if not isinstance(payload, dict):
        return {
            "enabled": True,
            "skill_name": module_name,
            "skill_version": "",
            "findings": [],
            "warning": "BMC Skill 返回格式无效；基础特征比对已正常完成。",
        }
    raw_findings = payload.get("findings", [])
    if not isinstance(raw_findings, list):
        return {
            "enabled": True,
            "skill_name": str(payload.get("skill_name") or module_name).strip()[:180],
            "skill_version": str(payload.get("skill_version") or "").strip()[:80],
            "findings": [],
            "warning": "BMC Skill 的 findings 必须是列表；基础特征比对已正常完成。",
        }
    findings = [item for index, raw in enumerate(raw_findings[:MAX_FINDINGS], start=1) if (item := _normalize_finding(raw, index))]
    return {
        "enabled": True,
        "skill_name": str(payload.get("skill_name") or module_name).strip()[:180],
        "skill_version": str(payload.get("skill_version") or "").strip()[:80],
        "findings": findings,
        "warning": str(payload.get("warning") or "").strip()[:600],
    }
