import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from fastapi import HTTPException

from app import database, main
from app.chat_sessions import touch_conversation
from tests.test_access_control import make_request


def endpoint(path, method):
    return next(route.endpoint for route in main.app.routes if route.path == path and method in route.methods)


class WeLinkModuleTests(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.previous_db_path = database.DB_PATH
        database.DB_PATH = Path(self.temp_dir.name) / "hub.db"
        database.init_db()
        self.db = database.connection()
        self.user_id = self.db.execute(
            "INSERT INTO users (username,password_hash,role) VALUES (?,?,?)", ("welink-owner", "not-used", "admin")
        ).lastrowid
        self.db.commit()

    def tearDown(self):
        self.db.close()
        database.DB_PATH = self.previous_db_path
        self.temp_dir.cleanup()

    def test_source_configuration_is_persisted_and_rendered(self):
        response = endpoint("/welink/sources", "POST")(
            make_request(self.user_id),
            source_type="notice_group",
            display_name="服务器问题通报群",
            conversation_key="group-001",
            note="验证配置",
            lookback_days=3,
        )
        self.assertEqual(303, response.status_code)
        source = self.db.execute("SELECT * FROM welink_sources").fetchone()
        self.assertEqual("notice_group", source["source_type"])
        self.assertEqual("group-001", source["conversation_key"])
        page = endpoint("/welink", "GET")(make_request(self.user_id))
        self.assertIn("服务器问题通报群", page.body.decode("utf-8"))

    def test_mode_switch_and_bulk_source_actions_have_working_routes(self):
        mode_response = endpoint("/welink/mode", "POST")(make_request(self.user_id), run_mode="demo")
        self.assertEqual(303, mode_response.status_code)
        self.assertIn("notice=mode_demo", mode_response.headers["location"])
        self.assertEqual("demo", self.db.execute("SELECT value FROM app_settings WHERE key='welink_run_mode'").fetchone()["value"])

        for name, key in (("群一", "group-1"), ("群二", "group-2"), ("群三", "group-3")):
            self.db.execute(
                "INSERT INTO welink_sources (source_type,display_name,conversation_key,created_by) VALUES ('notice_group',?,?,?)",
                (name, key, self.user_id),
            )
        self.db.commit()
        ids = [row["id"] for row in self.db.execute("SELECT id FROM welink_sources ORDER BY id").fetchall()]
        bulk_enable = endpoint("/welink/sources/bulk/{action}", "POST")(make_request(self.user_id), action="enable", source_ids="")
        self.assertEqual(303, bulk_enable.status_code)
        self.assertIn("notice=sources_enabled", bulk_enable.headers["location"])
        bulk_delete = endpoint("/welink/sources/bulk/{action}", "POST")(
            make_request(self.user_id), action="delete", source_ids=",".join(map(str, ids[:2]))
        )
        self.assertEqual(303, bulk_delete.status_code)
        self.assertIn("notice=sources_deleted", bulk_delete.headers["location"])
        self.assertEqual(1, self.db.execute("SELECT COUNT(*) AS count FROM welink_sources").fetchone()["count"])

    def test_primary_welink_buttons_return_redirects_not_route_errors(self):
        """Exercise every state-changing WeLink button with a valid demo setup."""
        endpoint("/welink", "GET")(make_request(self.user_id))  # Seeds demo issues and a conversation.
        source_response = endpoint("/welink/sources", "POST")(
            make_request(self.user_id),
            source_type="notice_group",
            display_name="按钮回归群",
            conversation_key="button-regression",
            note="导航回归",
            lookback_days=3,
        )
        recipient_response = endpoint("/welink/recipients", "POST")(
            make_request(self.user_id),
            recipient_type="group",
            display_name="按钮回归接收群",
            receiver_key="button-recipient",
        )
        self.assertEqual(303, source_response.status_code)
        self.assertEqual(303, recipient_response.status_code)
        source_id = self.db.execute("SELECT id FROM welink_sources ORDER BY id DESC LIMIT 1").fetchone()["id"]
        recipient_id = self.db.execute("SELECT id FROM welink_recipients ORDER BY id DESC LIMIT 1").fetchone()["id"]
        issue = self.db.execute("SELECT id FROM welink_issues ORDER BY id LIMIT 1").fetchone()
        action = self.db.execute("SELECT id FROM welink_issue_actions ORDER BY id LIMIT 1").fetchone()
        conversation = self.db.execute(
            "SELECT id FROM chat_conversations WHERE user_id=? AND scope='welink' ORDER BY id LIMIT 1", (self.user_id,)
        ).fetchone()

        calls = [
            ("/welink/mode", {"run_mode": "demo"}),
            ("/welink/reports/generate", {}),
            ("/welink/sources/bulk/{action}", {"action": "enable", "source_ids": ""}),
            ("/welink/sources/bulk/{action}", {"action": "disable", "source_ids": ""}),
            ("/welink/sources/bulk/{action}", {"action": "discussion", "source_ids": ""}),
            ("/welink/sources/{source_id}/{action}", {"source_id": source_id, "action": "toggle"}),
            ("/welink/sources/{source_id}/edit", {"source_id": source_id, "source_type": "notice_group", "display_name": "按钮回归群2", "conversation_key": "button-regression-2", "note": "", "lookback_days": 3}),
            ("/welink/recipients/{recipient_id}/{action}", {"recipient_id": recipient_id, "action": "toggle"}),
            ("/welink/recipients/{recipient_id}/edit", {"recipient_id": recipient_id, "recipient_type": "group", "display_name": "按钮回归接收群2", "receiver_key": "button-recipient-2"}),
            ("/welink/schedule", {"enabled": "1", "schedule_time": "08:00"}),
            ("/welink/runs", {}),
            ("/welink/issues/{issue_id}/status", {"issue_id": issue["id"], "status": "处理中"}),
            ("/welink/actions/{action_id}/toggle", {"action_id": action["id"]}),
            ("/welink/chat/conversations", {}),
            ("/welink/chat/conversations/{conversation_id}/rename", {"conversation_id": conversation["id"], "title": "按钮回归对话"}),
        ]
        for route_path, kwargs in calls:
            response = endpoint(route_path, "POST")(make_request(self.user_id), **kwargs)
            self.assertEqual(303, response.status_code, route_path)
            self.assertTrue(response.headers["location"].startswith("/welink"), route_path)

    def test_bulk_route_is_registered_before_dynamic_source_route(self):
        routes = [route.path for route in main.app.routes if route.path.startswith("/welink/sources/") and "POST" in route.methods]
        self.assertLess(routes.index("/welink/sources/bulk/{action}"), routes.index("/welink/sources/{source_id}/{action}"))

    def test_demo_run_never_reads_or_sends_messages(self):
        with patch.dict("os.environ", {"WELINK_AGENT_BRIDGE_URL": "", "WELINK_AGENT_BRIDGE_TOKEN": ""}):
            response = endpoint("/welink/runs", "POST")(make_request(self.user_id))
        self.assertEqual(303, response.status_code)
        run = self.db.execute("SELECT * FROM welink_runs").fetchone()
        self.assertEqual("completed", run["status"])
        self.assertIn("未连接 WeLink", run["summary"])

    def test_production_run_is_blocked_without_bridge_credentials(self):
        self.db.execute("INSERT INTO app_settings (key,value,updated_by) VALUES ('welink_run_mode','production',?)", (self.user_id,))
        self.db.execute(
            "INSERT INTO welink_sources (source_type,display_name,conversation_key,created_by) VALUES ('notice_group','生产通报群','prod-group',?)",
            (self.user_id,),
        )
        self.db.commit()
        with patch.dict("os.environ", {"WELINK_AGENT_BRIDGE_URL": "", "WELINK_AGENT_BRIDGE_TOKEN": ""}):
            response = endpoint("/welink/runs", "POST")(make_request(self.user_id))
        run = self.db.execute("SELECT * FROM welink_runs ORDER BY id DESC").fetchone()
        self.assertIsNone(run)
        self.assertIn("error=bridge", response.headers["location"])

    def test_active_production_run_blocks_duplicate_submission(self):
        self.db.execute("INSERT INTO app_settings (key,value,updated_by) VALUES ('welink_run_mode','production',?)", (self.user_id,))
        self.db.execute(
            "INSERT INTO welink_sources (source_type,display_name,conversation_key,created_by) VALUES ('notice_group','生产通报群','prod-group',?)",
            (self.user_id,),
        )
        self.db.commit()
        with patch.dict("os.environ", {"WELINK_AGENT_BRIDGE_URL": "https://bridge.invalid", "WELINK_AGENT_BRIDGE_TOKEN": "token"}), patch(
            "app.welink_module._bridge_run", return_value=("queued", "已入队")
        ):
            first = endpoint("/welink/runs", "POST")(make_request(self.user_id))
            second = endpoint("/welink/runs", "POST")(make_request(self.user_id))
        self.assertIn("notice=run_queued", first.headers["location"])
        self.assertIn("error=run_active", second.headers["location"])
        self.assertEqual(1, self.db.execute("SELECT COUNT(*) count FROM welink_runs").fetchone()["count"])

    def test_production_dashboard_never_displays_demo_issue_cards(self):
        endpoint("/welink", "GET")(make_request(self.user_id))  # Seeds explicit demo cards.
        self.db.execute("INSERT INTO app_settings (key,value,updated_by) VALUES ('welink_run_mode','production',?) ON CONFLICT(key) DO UPDATE SET value='production'", (self.user_id,))
        self.db.commit()
        page = endpoint("/welink", "GET")(make_request(self.user_id))
        self.assertNotIn("Atlas 900 节点 GPU 温度告警", page.body.decode("utf-8"))

    def test_reasoning_stream_is_delimited_before_final_answer(self):
        class FakeResponse:
            def __enter__(self): return self
            def __exit__(self, *_): return False
            def __iter__(self):
                return iter([
                    'data: {"choices":[{"delta":{"reasoning_content":"先检查证据"}}]}\n'.encode(),
                    'data: {"choices":[{"delta":{"reasoning_content":"，再判断风险"}}]}\n'.encode(),
                    'data: {"choices":[{"delta":{"content":"## 最终结论"}}]}\n'.encode(),
                    b'data: [DONE]\n',
                ])

        profile = {"id": "test", "name": "Test", "base_url": "https://model.invalid/v1", "model": "test", "api_key": "secret"}
        with patch.object(main, "active_llm_profile", return_value=profile), patch.object(main.urllib.request, "urlopen", return_value=FakeResponse()):
            chunks = list(main.llm_stream("question", "fallback", include_reasoning=True))
        self.assertEqual(
            [main.REASONING_START, "先检查证据", "，再判断风险", main.REASONING_END, "## 最终结论"],
            chunks,
        )

    def test_both_chat_pages_use_one_send_button_that_morphs_to_stop(self):
        welink_page = endpoint("/welink", "GET")(make_request(self.user_id)).body.decode("utf-8")
        ask_page = endpoint("/ask", "GET")(make_request(self.user_id)).body.decode("utf-8")
        self.assertNotIn('id="welink-stop"', welink_page)
        self.assertNotIn('id="ask-stop"', ask_page)
        self.assertEqual(welink_page.count('id="welink-send"'), 1)
        self.assertEqual(ask_page.count('id="ask-button"'), 1)
        self.assertIn("BmcChat.mount", welink_page)
        self.assertIn("BmcChat.mount", ask_page)
        runtime = (Path(__file__).resolve().parents[1] / "app/static/chat_runtime.js").read_text(encoding="utf-8")
        self.assertIn("running ? '停止'", runtime)
        self.assertIn("controller ? stop() : ask()", runtime)
        self.assertIn("Ctrl/⌘+Enter", welink_page)
        self.assertIn("Ctrl/⌘+Enter", ask_page)
        self.assertIn("AbortController", runtime)
        self.assertIn("sessionStorage", runtime)
        self.assertIn("回到最新", welink_page)
        self.assertIn("回到最新", ask_page)

    def test_reports_are_isolated_by_run_mode(self):
        endpoint("/welink/reports/generate", "POST")(make_request(self.user_id))
        self.db.execute(
            "INSERT INTO app_settings (key,value,updated_by) VALUES ('welink_run_mode','production',?) ON CONFLICT(key) DO UPDATE SET value='production'",
            (self.user_id,),
        )
        self.db.commit()
        production_page = endpoint("/welink", "GET")(make_request(self.user_id)).body.decode("utf-8")
        self.assertNotIn("巡检报告（演示数据）", production_page)
        endpoint("/welink/reports/generate", "POST")(make_request(self.user_id))
        reports = self.db.execute("SELECT run_mode,content FROM welink_reports ORDER BY id").fetchall()
        self.assertEqual(["demo", "production"], [row["run_mode"] for row in reports])
        self.assertIn("生产桥接数据", reports[-1]["content"])

    def test_new_chat_preserves_previous_conversation(self):
        first_page = endpoint("/ask", "GET")(make_request(self.user_id))
        self.assertEqual(200, first_page.status_code)
        first = self.db.execute("SELECT id FROM chat_conversations WHERE user_id=? AND scope='general'", (self.user_id,)).fetchone()
        response = endpoint("/ask/conversations", "POST")(make_request(self.user_id))
        second_id = int(response.headers["location"].split("=")[-1])
        self.assertNotEqual(first["id"], second_id)
        self.assertEqual(2, self.db.execute("SELECT COUNT(*) count FROM chat_conversations WHERE user_id=? AND scope='general'", (self.user_id,)).fetchone()["count"])

    def test_conversation_rename_is_shared_scoped_and_preserved(self):
        endpoint("/ask", "GET")(make_request(self.user_id))
        general = self.db.execute(
            "SELECT id FROM chat_conversations WHERE user_id=? AND scope='general'",
            (self.user_id,),
        ).fetchone()
        response = endpoint("/ask/conversations/{conversation_id}/rename", "POST")(
            make_request(self.user_id),
            conversation_id=general["id"],
            title="  Node-03   风扇告警复盘  ",
        )
        self.assertEqual(303, response.status_code)
        self.assertIn("notice=conversation_renamed", response.headers["location"])
        renamed = self.db.execute("SELECT title FROM chat_conversations WHERE id=?", (general["id"],)).fetchone()
        self.assertEqual("Node-03 风扇告警复盘", renamed["title"])
        touch_conversation(self.db, general["id"], "后续问题不应覆盖人工名称")
        self.db.commit()
        self.assertEqual(
            "Node-03 风扇告警复盘",
            self.db.execute("SELECT title FROM chat_conversations WHERE id=?", (general["id"],)).fetchone()["title"],
        )

        endpoint("/welink", "GET")(make_request(self.user_id))
        welink = self.db.execute(
            "SELECT id FROM chat_conversations WHERE user_id=? AND scope='welink' AND context_mode='demo'",
            (self.user_id,),
        ).fetchone()
        welink_response = endpoint("/welink/chat/conversations/{conversation_id}/rename", "POST")(
            make_request(self.user_id),
            conversation_id=welink["id"],
            title="每日重大问题跟踪",
        )
        self.assertEqual(303, welink_response.status_code)
        self.assertEqual(
            "每日重大问题跟踪",
            self.db.execute("SELECT title FROM chat_conversations WHERE id=?", (welink["id"],)).fetchone()["title"],
        )

        other_user = self.db.execute(
            "INSERT INTO users (username,password_hash,role) VALUES (?,?,?)",
            ("conversation-other", "not-used", "contributor"),
        ).lastrowid
        other_conversation = self.db.execute(
            "INSERT INTO chat_conversations (user_id,scope,context_mode,title) VALUES (?,?,?,?)",
            (other_user, "general", "", "他人的对话"),
        ).lastrowid
        self.db.commit()
        with self.assertRaises(HTTPException) as blocked:
            endpoint("/ask/conversations/{conversation_id}/rename", "POST")(
                make_request(self.user_id),
                conversation_id=other_conversation,
                title="越权修改",
            )
        self.assertEqual(404, blocked.exception.status_code)
        self.assertEqual(
            "他人的对话",
            self.db.execute("SELECT title FROM chat_conversations WHERE id=?", (other_conversation,)).fetchone()["title"],
        )

    def test_both_chat_pages_render_shared_conversation_rename_controls(self):
        ask_page = endpoint("/ask", "GET")(make_request(self.user_id)).body.decode("utf-8")
        welink_page = endpoint("/welink", "GET")(make_request(self.user_id)).body.decode("utf-8")
        for rendered in (ask_page, welink_page):
            self.assertIn("修改对话名称", rendered)
            self.assertIn("data-conversation-rename-open", rendered)
            self.assertIn('maxlength="60"', rendered)
            self.assertIn("保存名称", rendered)
        self.assertIn("/ask/conversations/", ask_page)
        self.assertIn("/welink/chat/conversations/", welink_page)
        interactions = (Path(__file__).resolve().parents[1] / "app/static/app_interactions.js").read_text(encoding="utf-8")
        self.assertIn("[data-conversation-switch]", interactions)
        self.assertIn("dialog.showModal()", interactions)
        self.assertIn("input?.select()", interactions)

    def test_question_streams_use_post_and_shared_chat_runtime(self):
        ask_route = next(route for route in main.app.routes if route.path == "/ask/stream")
        welink_route = next(route for route in main.app.routes if route.path == "/welink/chat/stream")
        self.assertEqual({"POST"}, ask_route.methods)
        self.assertEqual({"POST"}, welink_route.methods)
        runtime = (Path(__file__).resolve().parents[1] / "app/static/chat_runtime.js").read_text(encoding="utf-8")
        self.assertIn("method: 'POST'", runtime)
        self.assertIn("csrf_token", runtime)
        self.assertIn("sessionStorage", runtime)
        self.assertIn("STOP_ICON", runtime)
        self.assertIn("chat-button-glyph", runtime)

    def test_all_non_chat_llm_surfaces_share_stop_runtime(self):
        root = Path(__file__).resolve().parents[1]
        stream_script = (root / "app/templates/stream_script.html").read_text(encoding="utf-8")
        runtime = (root / "app/static/stream_runtime.js").read_text(encoding="utf-8")
        self.assertIn("BmcStream.mountAll()", stream_script)
        self.assertIn("AbortController", runtime)
        self.assertIn("停止", runtime)
        self.assertIn("aria-live", runtime)

    def test_welink_chat_aligns_full_width_and_config_lists_scroll(self):
        page = endpoint("/welink", "GET")(make_request(self.user_id)).body.decode("utf-8")
        self.assertIn('class="chat-shell welink-chat-shell glass"', page)
        self.assertIn(".welink-chat-shell{max-width:none", page)
        self.assertEqual(2, page.count("config-list managed-config-list"))
        self.assertIn('aria-label="已配置消息源列表"', page)
        self.assertIn('aria-label="已配置接收方列表"', page)
        self.assertIn("最多显示 3 个，列表内滚动", page)
        self.assertIn("max-height:min(450px,48vh)", page)
        template = (Path(__file__).resolve().parents[1] / "app/templates/welink.html").read_text(encoding="utf-8")
        self.assertIn('data-bulk-delete="source"', template)
        self.assertIn('data-bulk-item="source"', template)


if __name__ == "__main__":
    unittest.main()
