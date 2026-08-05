from collections.abc import Generator
from typing import Any

from dify_plugin import Tool
from dify_plugin.entities.tool import ToolInvokeMessage

from provider.pisces import PiscesError, error_message, pisces_request


class AddIocTool(Tool):
    def _invoke(self, tool_parameters: dict[str, Any]) -> Generator[ToolInvokeMessage, None, None]:
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

        try:
            resp = pisces_request(
                "POST", "/iocs", self.runtime.credentials,
                params={"incident_id": incident_id},
                json=body,
            )
        except PiscesError as e:
            yield self.create_text_message(f"请求失败: {e}")
            return

        if not resp.ok:
            yield self.create_text_message(
                f"添加 IOC 失败（{resp.status_code}）: {error_message(resp)}"
            )
            return

        data = resp.json()
        object_name = tool_parameters["object_name"]
        yield self.create_text_message(f"已成功添加 IOC: {object_name}")
        yield self.create_json_message(data)
