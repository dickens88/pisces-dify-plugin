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
        body: dict[str, Any] = {}

        # responses: one disposition object (or a JSON array of them) to append.
        responses = tool_parameters.get("responses")
        if responses is not None and str(responses).strip():
            try:
                parsed = json.loads(responses) if isinstance(responses, str) else responses
            except json.JSONDecodeError as e:
                yield self.create_text_message(f"响应处置（responses）不是合法的 JSON: {e}")
                return
            body["responses"] = parsed if isinstance(parsed, list) else [parsed]

        # behaviors: one behavior object (or a JSON array of them) to append.
        # The server stamps each one with a UTC update_time.
        behaviors = tool_parameters.get("behaviors")
        if behaviors is not None and str(behaviors).strip():
            try:
                parsed = json.loads(behaviors) if isinstance(behaviors, str) else behaviors
            except json.JSONDecodeError as e:
                yield self.create_text_message(f"行为数据（behaviors）不是合法的 JSON: {e}")
                return
            if isinstance(parsed, dict):  # a single record needs no array wrapper
                parsed = [parsed]
            if not isinstance(parsed, list):
                yield self.create_text_message(
                    "行为数据（behaviors）必须是一个 JSON 对象或对象数组，例如 "
                    '{"ip": "1.2.3.4", "service": "ssh", "action": "login"}。'
                )
                return
            bad = [i for i, item in enumerate(parsed) if not isinstance(item, dict)]
            if bad:
                yield self.create_text_message(
                    f"行为数据（behaviors）第 {', '.join(str(i + 1) for i in bad)} 项不是 JSON 对象，"
                    "数组中每一项都必须是对象。"
                )
                return
            if not parsed:
                yield self.create_text_message("行为数据（behaviors）是空数组，没有可追加的记录。")
                return
            body["behaviors"] = parsed

        # extra_fields: arbitrary MongoDB fields, written through as-is by the API.
        extra_fields = tool_parameters.get("extra_fields")
        if extra_fields is not None and str(extra_fields).strip():
            try:
                parsed = json.loads(extra_fields) if isinstance(extra_fields, str) else extra_fields
            except json.JSONDecodeError as e:
                yield self.create_text_message(f"附加字段（extra_fields）不是合法的 JSON: {e}")
                return
            if not isinstance(parsed, dict):
                yield self.create_text_message("附加字段（extra_fields）必须是一个 JSON 对象。")
                return
            body["extra_fields"] = parsed

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
