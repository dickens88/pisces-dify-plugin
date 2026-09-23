import json
from collections.abc import Generator
from typing import Any
from urllib.parse import quote

from dify_plugin import Tool
from dify_plugin.entities.tool import ToolInvokeMessage

from provider.pisces import PiscesError, error_message, pisces_request


class UpdateEntityProfileTool(Tool):
    def _invoke(self, tool_parameters: dict[str, Any]) -> Generator[ToolInvokeMessage, None, None]:
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

        force_update = bool(tool_parameters.get("force_update"))
        entity_type = str(tool_parameters.get("entity_type") or "tenant").strip()
        if force_update and entity_type != "tenant":
            yield self.create_text_message("强制同步（force_update）仅支持租户（entity_type=tenant）。")
            return

        if not body and not force_update:
            yield self.create_text_message("未提供任何要更新的字段。")
            return

        body["entity_type"] = entity_type
        if force_update:
            body["force_update"] = True

        path = f"/entities/{quote(str(object_name), safe='')}"
        try:
            resp = pisces_request("PATCH", path, self.runtime.credentials, json=body)
        except PiscesError as e:
            yield self.create_text_message(f"请求失败: {e}")
            return

        if resp.status_code == 404:
            yield self.create_text_message(
                f"未找到实体 {object_name} 的画像，且未能新建，无法更新。"
            )
            return
        if not resp.ok:
            yield self.create_text_message(
                f"更新实体画像失败（{resp.status_code}）: {error_message(resp)}"
            )
            return

        # The body is left unread: an API not yet upgraded still echoes the whole profile back.
        if not force_update:
            yield self.create_text_message(f"已更新实体 {object_name} 的画像信息。")
            yield self.create_json_message({"object_name": object_name, "updated": True})
            return

        synced = bool((resp.json() or {}).get("synced"))
        sync_note = "已从 Dify 同步基础信息" if synced else "Dify 未查到该租户的基础信息，未同步"
        yield self.create_text_message(f"已更新实体 {object_name} 的画像信息（{sync_note}）。")
        yield self.create_json_message({"object_name": object_name, "updated": True, "synced": synced})
