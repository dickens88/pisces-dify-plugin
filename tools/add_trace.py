from collections.abc import Generator
from typing import Any
from urllib.parse import quote

from dify_plugin import Tool
from dify_plugin.entities.tool import ToolInvokeMessage

from provider.pisces import PiscesError, error_message, pisces_request

# Trace states that mean a trace already exists — 溯源中 / 已完成.
EXISTING_TRACE_STATUSES = ("running", "complete")


class AddTraceTool(Tool):
    def _invoke(self, tool_parameters: dict[str, Any]) -> Generator[ToolInvokeMessage, None, None]:
        object_name = tool_parameters["object_name"]
        clue = str(tool_parameters.get("clue") or "").strip()
        encoded = quote(str(object_name), safe="")

        # 1) Look up the profile first to inspect the current trace status.
        try:
            resp = pisces_request("GET", f"/entities/{encoded}", self.runtime.credentials)
        except PiscesError as e:
            yield self.create_text_message(f"请求失败: {e}")
            return

        if resp.status_code == 404:
            yield self.create_text_message(f"未找到租户 {object_name} 的实体画像，无法添加溯源。")
            return
        if not resp.ok:
            yield self.create_text_message(
                f"查询实体画像失败（{resp.status_code}）: {error_message(resp)}"
            )
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

        # 3) No active trace — start one. 'running' is the only start state the API accepts;
        # it hands the task to Dify and notifies the tracer on duty, with the clue attached.
        try:
            put_resp = pisces_request(
                "PUT", f"/entities/{encoded}/trace", self.runtime.credentials,
                json={"status": "running", "clue": clue},
            )
        except PiscesError as e:
            yield self.create_text_message(f"请求失败: {e}")
            return

        if not put_resp.ok:
            yield self.create_text_message(
                f"添加溯源失败（{put_resp.status_code}）: {error_message(put_resp)}"
            )
            return

        data = put_resp.json()
        yield self.create_text_message(f"已为租户 {object_name} 添加溯源任务（状态: 溯源中），已通知值班溯源专员。")
        yield self.create_json_message(data)
