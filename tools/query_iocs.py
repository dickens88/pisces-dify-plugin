from collections.abc import Generator
from typing import Any

import requests
import urllib3
from dify_plugin import Tool
from dify_plugin.entities.tool import ToolInvokeMessage

urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

from provider.pisces import get_token


class QueryIocsTool(Tool):
    def _invoke(self, tool_parameters: dict[str, Any]) -> Generator[ToolInvokeMessage, None, None]:
        base_url = self.runtime.credentials["base_url"].rstrip("/")
        username = self.runtime.credentials["username"]
        password = self.runtime.credentials["password"]

        try:
            token = get_token(base_url, username, password)
        except Exception as e:
            yield self.create_text_message(f"登录失败: {e}")
            return

        params: dict[str, Any] = {
            "incident_id": tool_parameters["incident_id"],
            "limit": int(tool_parameters.get("limit") or 50),
            "offset": int(tool_parameters.get("offset") or 0),
        }
        if tool_parameters.get("object_type"):
            params["object_type"] = tool_parameters["object_type"]
        if tool_parameters.get("status"):
            params["status"] = tool_parameters["status"]

        url = f"{base_url}/incidents/iocs"
        try:
            resp = requests.get(
                url,
                params=params,
                headers={"Authorization": f"Bearer {token}"},
                timeout=30,
                verify=False,
            )
        except requests.exceptions.RequestException as e:
            yield self.create_text_message(f"请求失败: {e}")
            return

        if not resp.ok:
            body = resp.json() if resp.content else {}
            msg = body.get("error_message") or resp.text
            yield self.create_text_message(f"查询 IOC 失败（{resp.status_code}）: {msg}")
            return

        data = resp.json()
        total = data.get("total", 0)
        iocs = data.get("data", [])
        yield self.create_text_message(f"共 {total} 条 IOC，本次返回 {len(iocs)} 条。")
        yield self.create_json_message(data)
