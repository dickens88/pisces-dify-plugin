import json
from collections.abc import Generator
from typing import Any
from urllib.parse import quote

import requests
import urllib3
from dify_plugin import Tool
from dify_plugin.entities.tool import ToolInvokeMessage

urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

from provider.pisces import get_token

# tenant_tags.* fields exposed as simple string/select params.
TENANT_TAG_PARAMS = ("security_tag", "attacker_type", "remark")


class UpdateEntityProfileTool(Tool):
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

        tenant_tags: dict[str, Any] = {}
        for key in TENANT_TAG_PARAMS:
            val = tool_parameters.get(key)
            if val is not None and str(val).strip() != "":
                tenant_tags[key] = val

        # user_tags: accept a comma-separated string, store as a list.
        user_tags_raw = tool_parameters.get("user_tags")
        if user_tags_raw is not None and str(user_tags_raw).strip() != "":
            tenant_tags["user_tags"] = [t.strip() for t in str(user_tags_raw).split(",") if t.strip()]

        body: dict[str, Any] = {}
        if tenant_tags:
            body["tenant_tags"] = tenant_tags

        # responses: a JSON array of disposition records (replaces the stored list).
        responses = tool_parameters.get("responses")
        if isinstance(responses, str):
            responses = responses.strip()
            if responses:
                try:
                    responses = json.loads(responses)
                except json.JSONDecodeError as e:
                    yield self.create_text_message(f"响应处置（responses）不是合法的 JSON: {e}")
                    return
            else:
                responses = None
        if responses is not None:
            if not isinstance(responses, list):
                yield self.create_text_message("响应处置（responses）必须是一个 JSON 数组。")
                return
            body["responses"] = responses

        if not body:
            yield self.create_text_message("未提供任何要更新的字段。")
            return

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

        if resp.status_code == 404:
            yield self.create_text_message(f"未找到实体 {object_name} 的画像，无法更新。")
            return
        if not resp.ok:
            resp_body = resp.json() if resp.content else {}
            msg = resp_body.get("error_message") or resp.text
            yield self.create_text_message(f"更新实体画像失败（{resp.status_code}）: {msg}")
            return

        data = resp.json()
        yield self.create_text_message(f"已更新实体 {object_name} 的画像信息。")
        yield self.create_json_message(data)
