from collections.abc import Generator
from typing import Any
from urllib.parse import quote

import requests
import urllib3
from dify_plugin import Tool
from dify_plugin.entities.tool import ToolInvokeMessage

urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

from provider.pisces import get_token

# Trace states that mean a trace already exists — 溯源中 / 已完成.
EXISTING_TRACE_STATUSES = ("running", "complete")


class AddTraceTool(Tool):
    def _invoke(self, tool_parameters: dict[str, Any]) -> Generator[ToolInvokeMessage, None, None]:
        base_url = self.runtime.credentials["base_url"].rstrip("/")
        username = self.runtime.credentials["username"]
        password = self.runtime.credentials["password"]

        try:
            token = get_token(base_url, username, password)
        except Exception as e:
            yield self.create_text_message(f"登录失败: {e}")
            return

        object_name = tool_parameters["object_name"]
        headers = {"Authorization": f"Bearer {token}"}
        encoded = quote(str(object_name), safe="")

        # 1) Look up the profile first to inspect the current trace status.
        try:
            resp = requests.get(
                f"{base_url}/entities/{encoded}",
                headers=headers,
                timeout=30,
                verify=False,
            )
        except requests.exceptions.RequestException as e:
            yield self.create_text_message(f"请求失败: {e}")
            return

        if resp.status_code == 404:
            yield self.create_text_message(f"未找到租户 {object_name} 的实体画像，无法添加溯源。")
            return
        if not resp.ok:
            body = resp.json() if resp.content else {}
            msg = body.get("error_message") or resp.text
            yield self.create_text_message(f"查询实体画像失败（{resp.status_code}）: {msg}")
            return

        profile = (resp.json() or {}).get("data") or {}
        trace_status = ((profile.get("tenant_tags") or {}).get("trace_status")) or None

        # 2) Already tracing or finished — return the existing record instead of re-adding.
        if trace_status in EXISTING_TRACE_STATUSES:
            label = "溯源中" if trace_status == "running" else "已完成"
            yield self.create_text_message(
                f"租户 {object_name} 已有溯源记录（状态: {label}）。"
            )
            yield self.create_json_message(
                {"object_name": object_name, "trace_status": trace_status, "existing": True, "data": profile}
            )
            return

        # 3) No active trace — add one and set the status to waiting.
        try:
            put_resp = requests.put(
                f"{base_url}/entities/{encoded}/trace",
                json={"status": "waiting"},
                headers=headers,
                timeout=30,
                verify=False,
            )
        except requests.exceptions.RequestException as e:
            yield self.create_text_message(f"请求失败: {e}")
            return

        if not put_resp.ok:
            body = put_resp.json() if put_resp.content else {}
            msg = body.get("error_message") or put_resp.text
            yield self.create_text_message(f"添加溯源失败（{put_resp.status_code}）: {msg}")
            return

        data = put_resp.json()
        yield self.create_text_message(f"已为租户 {object_name} 添加溯源任务（状态: waiting）。")
        yield self.create_json_message(data)
