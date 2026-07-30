import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


class WindowsCompatibilityTests(unittest.TestCase):
    def test_browser_capability_guard_is_loaded(self):
        base = (ROOT / "app/templates/base.html").read_text(encoding="utf-8")
        guard = (ROOT / "app/static/browser_compat.js").read_text(encoding="utf-8")
        self.assertIn("browser_compat.js", base)
        for capability in ("fetch", "ReadableStream", "AbortController", "TextDecoder"):
            self.assertIn(capability, guard)

    def test_nginx_streaming_is_not_buffered(self):
        nginx = (ROOT / "deploy/nginx-bmc-hub.conf").read_text(encoding="utf-8")
        self.assertIn("proxy_buffering off", nginx)
        self.assertIn("proxy_cache off", nginx)
        self.assertIn("proxy_read_timeout 300s", nginx)
        self.assertIn("welink/chat/stream", nginx)

    def test_deployment_guide_explains_windows_server_topology(self):
        guide = (ROOT / "deploy/OPEN_EULER_24_03_X86_64.md").read_text(encoding="utf-8")
        self.assertIn("Windows 电脑上的 Edge/Chrome", guide)
        self.assertIn("Windows 用户不能访问文档中的 `127.0.0.1:8000`", guide)
        self.assertIn("openEuler 24.03 x86_64", guide)
        self.assertIn("Python 3.11", guide)


if __name__ == "__main__":
    unittest.main()
