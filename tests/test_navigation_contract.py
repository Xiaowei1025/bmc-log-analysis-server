"""Static navigation and form contracts for every template action.

These tests are intentionally framework-level rather than tied to one page. A
button whose action is renamed without updating its route should fail the suite
before it reaches a browser. The browser smoke pass remains useful for visual
and JavaScript-only behavior, while this contract catches broken links and
missing POST endpoints across the whole platform.
"""

import re
import unittest
from pathlib import Path
from urllib.parse import urlsplit

from app import main


ROOT = Path(__file__).resolve().parents[1]
TEMPLATE_DIR = ROOT / "app" / "templates"


def _routes():
    return [
        (route.path, set(route.methods))
        for route in main.app.routes
        if hasattr(route, "path") and hasattr(route, "methods")
    ]


def _route_matches(path, method):
    path = urlsplit(path).path or "/"
    for route_path, methods in _routes():
        if method not in methods:
            continue
        expression = "^" + re.sub(r"\{[^}]+\}", r"[^/]+", route_path) + "$"
        if re.match(expression, path):
            return route_path
    return None


def _render_path(value):
    """Make a representative URL from a Jinja template expression."""
    value = re.sub(r"\{\{\s*mode\s*\}\}", "login", value)
    return re.sub(r"\{\{.*?\}\}", "1", value)


def _local(value):
    return value.startswith("/") and not value.startswith("//") and not value.startswith("/static")


class NavigationContractTests(unittest.TestCase):
    def test_every_template_link_stream_and_form_action_has_a_route(self):
        """Catch buttons that navigate to a typo or an unregistered endpoint."""
        missing = []
        for template in sorted(TEMPLATE_DIR.glob("*.html")):
            source = template.read_text(encoding="utf-8")
            for value in re.findall(r'href="([^"]+)"', source):
                if _local(value):
                    path = _render_path(value)
                    if not _route_matches(path, "GET"):
                        missing.append(f"{template.name}: GET {value}")
            for tag in re.findall(r"<form\b[^>]*>", source, flags=re.IGNORECASE | re.DOTALL):
                action = re.search(r'action="([^"]+)"', tag)
                if not action or not _local(action.group(1)):
                    continue
                method = (re.search(r'method="([^"]+)"', tag) or [None, "get"])[1].upper()
                path = _render_path(action.group(1))
                if not _route_matches(path, method):
                    missing.append(f"{template.name}: {method} {action.group(1)}")
            for value in re.findall(r'data-stream-url="([^"]+)"', source):
                if _local(value) and not _route_matches(_render_path(value), "GET"):
                    missing.append(f"{template.name}: stream GET {value}")
        self.assertEqual([], missing, "navigation target has no matching registered route")

    def test_every_state_changing_template_form_has_csrf_protection(self):
        """Prevent a new button from bypassing the platform's POST guard."""
        missing = []
        for template in sorted(TEMPLATE_DIR.glob("*.html")):
            source = template.read_text(encoding="utf-8")
            for match in re.finditer(r"<form\b([^>]*)>(.*?)</form>", source, flags=re.IGNORECASE | re.DOTALL):
                attributes, body = match.groups()
                method = re.search(r'method="([^"]+)"', attributes)
                if method and method.group(1).lower() == "post" and "csrf" not in body.lower():
                    form_id = re.search(r'id="([^"]+)"', attributes)
                    associated = form_id and re.search(
                        rf'name="csrf_token"[^>]*form="{re.escape(form_id.group(1))}"',
                        source,
                        flags=re.IGNORECASE | re.DOTALL,
                    )
                    if not associated:
                        missing.append(f"{template.name}: {attributes.strip()}")
        self.assertEqual([], missing, "POST form is missing a CSRF field")

    def test_destructive_buttons_are_confirmed_before_submission(self):
        """Delete/discard controls must provide an explicit confirmation step."""
        missing = []
        for template in sorted(TEMPLATE_DIR.glob("*.html")):
            source = template.read_text(encoding="utf-8")
            for match in re.finditer(r"<form\b([^>]*)>(.*?)</form>", source, flags=re.IGNORECASE | re.DOTALL):
                attributes, body = match.groups()
                action = re.search(r'action="([^"]*(?:delete|discard)[^"]*)"', attributes)
                if action and "data-confirm" not in attributes and "confirm(" not in attributes:
                    missing.append(f"{template.name}: {action.group(1)}")
        self.assertEqual([], missing, "destructive form has no confirmation")

    def test_redirect_literals_point_to_registered_get_routes(self):
        """Catch successful POST handlers that redirect to a removed page."""
        missing = []
        pattern = re.compile(r"redirect\(f?([\"'])(/[^\"']*)\1")
        for module in (ROOT / "app" / "main.py", ROOT / "app" / "welink_module.py"):
            source = module.read_text(encoding="utf-8")
            for value in pattern.findall(source):
                target = value[1].split("?", 1)[0].split("#", 1)[0]
                target = re.sub(r"\{[^}]*\}", "1", target)
                if not _route_matches(target, "GET"):
                    missing.append(f"{module.name}: {target}")
        self.assertEqual([], missing, "redirect target has no registered GET route")


if __name__ == "__main__":
    unittest.main()
