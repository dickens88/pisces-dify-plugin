from collections.abc import Generator
from typing import Any
from urllib.parse import quote

from dify_plugin import Tool
from dify_plugin.entities.tool import ToolInvokeMessage

from provider.pisces import PiscesError, error_message, pisces_request

STATUS_LABELS = {
    "idle": "空闲",
    "running": "运行中",
    "stopped": "已停止",
    "error": "出错",
}


class QueryDeeptraceStatusTool(Tool):
    def _invoke(self, tool_parameters: dict[str, Any]) -> Generator[ToolInvokeMessage, None, None]:
        session_id = tool_parameters["session_id"]
        path = f"/deeptrace/sessions/{quote(str(session_id), safe='')}"
        try:
            resp = pisces_request("GET", path, self.runtime.credentials)
        except PiscesError as e:
            yield self.create_text_message(f"请求失败: {e}")
            return

        if resp.status_code == 404:
            yield self.create_text_message(f"未找到Deeptrace会话 {session_id}。")
            return
        if not resp.ok:
            yield self.create_text_message(
                f"查询任务状态失败（{resp.status_code}）: {error_message(resp)}"
            )
            return

        session = (resp.json() or {}).get("data") or {}
        status = session.get("status") or "unknown"
        label = STATUS_LABELS.get(status, status)
        title = session.get("title") or ""
        yield self.create_text_message(
            f"Deeptrace会话 {session_id}（{title}）当前状态: {label}。"
        )
        yield self.create_json_message(session)
