from collections.abc import Generator
from typing import Any
from urllib.parse import quote

import requests
import urllib3
from dify_plugin import Tool
from dify_plugin.entities.tool import ToolInvokeMessage

urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

from provider.pisces import get_token


class QueryEntityProfileTool(Tool):
    def _invoke(self, tool_parameters: dict[str, Any]) -> Generator[ToolInvokeMessage, None, None]:
        base_url = self.runtime.credentials["base_url"].rstrip("/")
        username = self.runtime.credentials["username"]
        password = self.runtime.credentials["password"]

        try:
            token = get_token(base_url, username, password)
        except Exception as e:
            yield self.create_text_message(f"登录失败: {e}")
            return

        headers = {"Authorization": f"Bearer {token}"}
        object_name = tool_parameters.get("object_name")

        if object_name:
            url = f"{base_url}/entities/{quote(str(object_name), safe='')}"
            try:
                resp = requests.get(url, headers=headers, timeout=30, verify=False)
            except requests.exceptions.RequestException as e:
                yield self.create_text_message(f"请求失败: {e}")
                return

            if not resp.ok:
                body = resp.json() if resp.content else {}
                msg = body.get("error_message") or resp.text
                yield self.create_text_message(f"查询实体画像失败（{resp.status_code}）: {msg}")
                return

            data = resp.json()
            yield self.create_text_message(f"已获取实体 {object_name} 的画像信息。")
            yield self.create_json_message(data)
            return

        # object_name omitted — list/search profiles instead, optionally filtered by monitoring state.
        monitoring = tool_parameters.get("monitoring")
        params: dict[str, Any] = {
            "limit": int(tool_parameters.get("limit") or 50),
            "offset": int(tool_parameters.get("offset") or 0),
        }
        if monitoring is not None:
            params["monitoring"] = "true" if bool(monitoring) else "false"
        # A switch, not a tri-state: the API filters on an exact security_tag value,
        # so "off" means no filter rather than "everything except attackers".
        if tool_parameters.get("attacker_only"):
            params["security_tag"] = "attack"

        try:
            resp = requests.get(f"{base_url}/entities", headers=headers, params=params, timeout=30, verify=False)
        except requests.exceptions.RequestException as e:
            yield self.create_text_message(f"请求失败: {e}")
            return

        if not resp.ok:
            body = resp.json() if resp.content else {}
            msg = body.get("error_message") or resp.text
            yield self.create_text_message(f"查询实体画像列表失败（{resp.status_code}）: {msg}")
            return

        data = resp.json()
        total = data.get("total", 0)
        rows = data.get("data", [])
        scope = {"true": "已添加盯防的", "false": "未添加盯防的"}.get(params.get("monitoring"), "")
        if params.get("security_tag") == "attack":
            scope += "攻击者"
        yield self.create_text_message(f"{scope}实体画像共 {total} 条，本次返回 {len(rows)} 条。")
        yield self.create_json_message(data)
