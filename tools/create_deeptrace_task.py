from collections.abc import Generator
from typing import Any

import requests
from dify_plugin import Tool
from dify_plugin.entities.tool import ToolInvokeMessage

from provider.pisces import get_token


class CreateDeeptraceTaskTool(Tool):
    def _invoke(self, tool_parameters: dict[str, Any]) -> Generator[ToolInvokeMessage, None, None]:
        base_url = self.runtime.credentials["base_url"].rstrip("/")
        username = self.runtime.credentials["username"]
        password = self.runtime.credentials["password"]

        try:
            token = get_token(base_url, username, password)
        except Exception as e:
            yield self.create_text_message(f"登录失败: {e}")
            return

        headers = {"Authorization": f"Bearer {token}", "Content-Type": "application/json"}
        title = (tool_parameters.get("title") or "").strip()
        question = (tool_parameters.get("question") or "").strip()
        if not question:
            yield self.create_text_message("question 为必填参数")
            return

        # Step 1: Create session
        try:
            resp = requests.post(
                f"{base_url}/deeptrace/sessions",
                json={"title": title or question[:100]},
                headers=headers,
                timeout=15,
            )
        except requests.exceptions.RequestException as e:
            yield self.create_text_message(f"创建会话失败: {e}")
            return

        if not resp.ok:
            body = resp.json() if resp.content else {}
            msg = body.get("error_message") or body.get("error") or resp.text
            yield self.create_text_message(f"创建会话失败（{resp.status_code}）: {msg}")
            return

        session = resp.json().get("data", {})
        session_id = session.get("session_id")
        if not session_id:
            yield self.create_text_message(f"创建会话成功但未返回 session_id: {resp.text}")
            return

        # Step 2: Start run (send question)
        msg_body: dict[str, Any] = {"text": question}
        model = (tool_parameters.get("model") or "").strip()
        if model:
            msg_body["model"] = model

        try:
            resp2 = requests.post(
                f"{base_url}/deeptrace/sessions/{session_id}/messages",
                json=msg_body,
                headers=headers,
                timeout=15,
            )
        except requests.exceptions.RequestException as e:
            yield self.create_text_message(f"会话已创建（{session_id}）但启动任务失败: {e}")
            return

        if not resp2.ok:
            body2 = resp2.json() if resp2.content else {}
            msg2 = body2.get("error_message") or body2.get("error") or resp2.text
            yield self.create_text_message(f"会话已创建（{session_id}）但启动任务失败（{resp2.status_code}）: {msg2}")
            return

        yield self.create_text_message(f"深度溯源任务已创建并启动，session_id: {session_id}")
        yield self.create_json_message({
            "session_id": session_id,
            "title": session.get("title", ""),
            "status": "running",
        })
