from collections.abc import Generator
from typing import Any

import requests
import urllib3
from dify_plugin import Tool
from dify_plugin.entities.tool import ToolInvokeMessage

urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

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
        session_body: dict[str, Any] = {"title": title or question[:100]}
        # alert_id links the session to that alert as a shared investigation.
        alert_id = (tool_parameters.get("alert_id") or "").strip()
        if alert_id:
            session_body["alert_id"] = alert_id
        else:
            session_body["source"] = "dify"  # groups it under DeepTrace's system tab
        model = (tool_parameters.get("model") or "").strip()
        if model:
            # Set here too so session.model (shown in the UI) matches the run.
            session_body["model"] = model

        try:
            resp = requests.post(
                f"{base_url}/deeptrace/sessions",
                json=session_body,
                headers=headers,
                timeout=15,
                verify=False,
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
        if model:
            msg_body["model"] = model

        try:
            resp2 = requests.post(
                f"{base_url}/deeptrace/sessions/{session_id}/messages",
                json=msg_body,
                headers=headers,
                timeout=15,
                verify=False,
            )
        except requests.exceptions.RequestException as e:
            yield self.create_text_message(f"会话已创建（{session_id}）但启动任务失败: {e}")
            return

        if not resp2.ok:
            body2 = resp2.json() if resp2.content else {}
            msg2 = body2.get("error_message") or body2.get("error") or resp2.text
            yield self.create_text_message(f"会话已创建（{session_id}）但启动任务失败（{resp2.status_code}）: {msg2}")
            return

        linked = f"，已关联告警 {alert_id}" if alert_id else ""
        yield self.create_text_message(f"Deeptrace任务已创建并启动，session_id: {session_id}{linked}")
        result: dict[str, Any] = {
            "session_id": session_id,
            "title": session.get("title", ""),
            "status": "running",
        }
        if alert_id:
            result["alert_id"] = alert_id
        yield self.create_json_message(result)
