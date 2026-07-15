from collections.abc import Generator
from typing import Any
from urllib.parse import quote

import requests
import urllib3
from dify_plugin import Tool
from dify_plugin.entities.tool import ToolInvokeMessage

urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

from provider.pisces import get_token


class AddMonitoringTool(Tool):
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
        # monitoring defaults to enabling the tag; pass false to remove it.
        enable = tool_parameters.get("enable")
        enable = True if enable is None else bool(enable)

        tenant_tags: dict[str, Any] = {"monitoring": enable}
        remark = tool_parameters.get("remark")
        if remark is not None and str(remark).strip() != "":
            tenant_tags["remark"] = remark

        body = {"tenant_tags": tenant_tags}
        url = f"{base_url}/entities/{quote(str(object_name), safe='')}"
        try:
            resp = requests.patch(
                url,
                json=body,
                headers={"Authorization": f"Bearer {token}"},
                timeout=30,
                verify=False,
            )
        except requests.exceptions.RequestException as e:
            yield self.create_text_message(f"请求失败: {e}")
            return

        if not resp.ok:
            resp_body = resp.json() if resp.content else {}
            msg = resp_body.get("error_message") or resp.text
            action = "添加盯防" if enable else "取消盯防"
            yield self.create_text_message(f"{action}失败（{resp.status_code}）: {msg}")
            return

        data = resp.json()
        action = "已添加盯防标记" if enable else "已取消盯防标记"
        yield self.create_text_message(f"{action}: {object_name}")
        yield self.create_json_message(data)
