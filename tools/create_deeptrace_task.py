from collections.abc import Generator
from typing import Any

from dify_plugin import Tool
from dify_plugin.entities.tool import ToolInvokeMessage

from provider.pisces import PiscesError, error_message, pisces_request


class CreateDeeptraceTaskTool(Tool):
    def _invoke(self, tool_parameters: dict[str, Any]) -> Generator[ToolInvokeMessage, None, None]:
        title = (tool_parameters.get("title") or "").strip()
        question = (tool_parameters.get("question") or "").strip()
        if not question:
            yield self.create_text_message("question 为必填参数")
            return

        session_body: dict[str, Any] = {"title": title or question[:100], "source": "dify"}
        # alert_id links the session to that alert as a shared investigation.
        alert_id = (tool_parameters.get("alert_id") or "").strip()
        if alert_id:
            session_body["alert_id"] = alert_id
        model = (tool_parameters.get("model") or "").strip()
        if model:
            # Set here too so session.model (shown in the UI) matches the run.
            session_body["model"] = model

        try:
            resp = pisces_request(
                "POST", "/deeptrace/sessions", self.runtime.credentials,
                json=session_body,
                timeout=15,
            )
        except PiscesError as e:
            yield self.create_text_message(f"创建会话失败: {e}")
            return

        if not resp.ok:
            yield self.create_text_message(
                f"创建会话失败（{resp.status_code}）: {error_message(resp)}"
            )
            return

        session = resp.json().get("data", {})
        session_id = session.get("session_id")
        if not session_id:
            yield self.create_text_message(f"创建会话成功但未返回 session_id: {resp.text}")
            return

        # Posting the question is what actually starts the run.
        msg_body: dict[str, Any] = {"text": question}
        if model:
            msg_body["model"] = model

        try:
            resp2 = pisces_request(
                "POST", f"/deeptrace/sessions/{session_id}/messages", self.runtime.credentials,
                json=msg_body,
                timeout=15,
            )
        except PiscesError as e:
            yield self.create_text_message(f"会话已创建（{session_id}）但启动任务失败: {e}")
            return

        if not resp2.ok:
            yield self.create_text_message(
                f"会话已创建（{session_id}）但启动任务失败（{resp2.status_code}）: {error_message(resp2)}"
            )
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
