"""Windows-side WeLink connector MVP.

This client deliberately has no shell execution and no guessed WeLink CLI
syntax.  Replace ``WeLinkCliAdapter`` with the company-approved fixed command
mapping after the internal CLI contract is supplied.
"""

from __future__ import annotations

import argparse
import json
import time
import urllib.error
import urllib.request
from pathlib import Path


class WeLinkCliAdapter:
    def __init__(self, cli_path: str, dry_run: bool = False):
        self.cli_path = cli_path
        self.dry_run = dry_run

    def inspect(self, payload: dict) -> dict:
        if self.dry_run:
            return {"ok": True, "summary": "连接器 dry-run：未调用 WeLink CLI。", "issues": []}
        if not self.cli_path:
            return {"ok": False, "error": "未配置公司批准的 WeLink CLI 路径。"}
        # Intentionally fail closed until the company supplies the exact,
        # versioned subcommands and JSON schema. Never concatenate payload into
        # a shell command or accept arbitrary executable arguments from HTTP.
        return {"ok": False, "error": "WeLinkCliAdapter 尚未绑定公司内部 CLI 命令白名单。"}


class Connector:
    def __init__(self, config: dict):
        self.server_url = str(config["server_url"]).rstrip("/")
        self.token = str(config["token"])
        self.poll_seconds = max(3, int(config.get("poll_seconds", 10)))
        self.adapter = WeLinkCliAdapter(str(config.get("cli_path", "")), bool(config.get("dry_run", False)))

    def request(self, method: str, path: str, payload: dict | None = None) -> dict:
        body = json.dumps(payload or {}, ensure_ascii=False).encode("utf-8") if payload is not None else None
        request = urllib.request.Request(self.server_url + path, data=body, method=method, headers={"Authorization": "Bearer " + self.token, "Content-Type": "application/json"})
        with urllib.request.urlopen(request, timeout=20) as response:
            return json.loads(response.read().decode("utf-8"))

    def run_once(self) -> bool:
        self.request("POST", "/api/welink/connectors/heartbeat", {"capabilities": ["inspection", "delivery", "dry-run" if self.adapter.dry_run else "cli"]})
        result = self.request("GET", "/api/welink/connectors/jobs")
        job = result.get("job")
        if not job:
            return False
        lease = job["lease_token"]
        self.request("POST", f"/api/welink/connectors/jobs/{job['id']}/ack", {"lease_token": lease, "state": "running"})
        output = self.adapter.inspect(job.get("payload") or {})
        output["lease_token"] = lease
        self.request("POST", f"/api/welink/connectors/jobs/{job['id']}/result", output)
        return True

    def run_forever(self):
        while True:
            try:
                self.run_once()
            except (OSError, ValueError, KeyError, urllib.error.URLError) as error:
                print(f"connector error: {error}", flush=True)
            time.sleep(self.poll_seconds)


def main():
    parser = argparse.ArgumentParser(description="BMC WeLink Windows connector")
    parser.add_argument("--config", default="config.json")
    parser.add_argument("--once", action="store_true", help="只执行一次心跳和任务轮询")
    args = parser.parse_args()
    config = json.loads(Path(args.config).read_text(encoding="utf-8"))
    connector = Connector(config)
    connector.run_once() if args.once else connector.run_forever()


if __name__ == "__main__":
    main()
