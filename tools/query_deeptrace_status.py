from collections.abc import Generator
from typing import Any
from urllib.parse import quote

import requests
import urllib3
from dify_plugin import Tool
from dify_plugin.entities.tool import ToolInvokeMessage

urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

from provider.pisces import get_token

STATUS_LABELS = {
    "idle": "空闲",
    "running": "运行中",
    "stopped": "已停止",
    "error": "出错",
}


class QueryDeeptraceStatusTool(Tool):
    def _invoke(self, tool_parameters: dict[str, Any]) -> Generator[ToolInvokeMessage, None, None]:
        base_url = self.runtime.credentials["base_url"].rstrip("/")
        username = self.runtime.credentials["username"]
        password = self.runtime.credentials["password"]

        try:
            token = get_token(base_url, username, password)
        except Exception as e:
            yield self.create_text_message(f"登录失败: {e}")
            return

        session_id = tool_parameters["session_id"]
        url = f"{base_url}/deeptrace/sessions/{quote(str(session_id), safe='')}"
        try:
            resp = requests.get(
                url,
                headers={"Authorization": f"Bearer {token}"},
                timeout=30,
                verify=False,
            )
        except requests.exceptions.RequestException as e:
            yield self.create_text_message(f"请求失败: {e}")
            return

        if resp.status_code == 404:
            yield self.create_text_message(f"未找到Deeptrace会话 {session_id}。")
            return
        if not resp.ok:
            body = resp.json() if resp.content else {}
            msg = body.get("error_message") or body.get("error") or resp.text
            yield self.create_text_message(f"查询任务状态失败（{resp.status_code}）: {msg}")
            return

        session = (resp.json() or {}).get("data") or {}
        status = session.get("status") or "unknown"
        label = STATUS_LABELS.get(status, status)
        title = session.get("title") or ""
        yield self.create_text_message(
            f"Deeptrace会话 {session_id}（{title}）当前状态: {label}。"
        )
        yield self.create_json_message(session)
