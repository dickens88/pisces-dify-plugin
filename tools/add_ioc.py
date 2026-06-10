from collections.abc import Generator
from typing import Any

import requests
from dify_plugin import Tool
from dify_plugin.entities.tool import ToolInvokeMessage

from provider.pisces import get_token


class AddIocTool(Tool):
    def _invoke(self, tool_parameters: dict[str, Any]) -> Generator[ToolInvokeMessage, None, None]:
        base_url = self.runtime.credentials["base_url"].rstrip("/")
        username = self.runtime.credentials["username"]
        password = self.runtime.credentials["password"]

        try:
            token = get_token(base_url, username, password)
        except Exception as e:
            yield self.create_text_message(f"登录失败: {e}")
            return

        incident_id = tool_parameters["incident_id"]

        body: dict[str, Any] = {
            "object_name": tool_parameters["object_name"],
            "object_type": tool_parameters["object_type"],
            "object_subtype": tool_parameters["object_subtype"],
        }
        for optional in ("object_label", "object_detail", "source", "handle_status", "status", "alert_id"):
            value = tool_parameters.get(optional)
            if value is not None and str(value).strip():
                body[optional] = value

        url = f"{base_url}/incidents/{incident_id}/iocs"
        try:
            resp = requests.post(
                url,
                json=body,
                headers={"Authorization": f"Bearer {token}"},
                timeout=30,
            )
        except requests.exceptions.RequestException as e:
            yield self.create_text_message(f"请求失败: {e}")
            return

        if not resp.ok:
            resp_body = resp.json() if resp.content else {}
            msg = resp_body.get("error_message") or resp.text
            yield self.create_text_message(f"添加 IOC 失败（{resp.status_code}）: {msg}")
            return

        data = resp.json()
        object_name = tool_parameters["object_name"]
        yield self.create_text_message(f"已成功添加 IOC: {object_name}")
        yield self.create_json_message(data)
