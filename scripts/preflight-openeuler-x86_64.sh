#!/usr/bin/env bash
set -euo pipefail

fail() { echo "[失败] $*" >&2; exit 1; }

[[ "$(uname -m)" == "x86_64" ]] || fail "目标架构必须为 x86_64，当前为 $(uname -m)"
command -v python3.11 >/dev/null || fail "未找到 python3.11"
python3.11 - <<'PY'
import sys
assert sys.version_info[:2] == (3, 11), sys.version
print(f"[通过] Python {sys.version.split()[0]}")
PY
[[ -f /etc/os-release ]] || fail "未找到 /etc/os-release"
grep -qi 'openEuler' /etc/os-release || fail "目标系统不是 openEuler"
command -v nginx >/dev/null || echo "[提示] 未找到 nginx；部署前请安装"
echo "[通过] openEuler x86_64 Python 3.11 前置检查完成"
