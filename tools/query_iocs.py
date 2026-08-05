from collections.abc import Generator
from typing import Any

from dify_plugin import Tool
from dify_plugin.entities.tool import ToolInvokeMessage

from provider.pisces import PiscesError, error_message, pisces_request


class QueryIocsTool(Tool):
    def _invoke(self, tool_parameters: dict[str, Any]) -> Generator[ToolInvokeMessage, None, None]:
        params: dict[str, Any] = {
            "incident_id": tool_parameters["incident_id"],
            "limit": int(tool_parameters.get("limit") or 50),
            "offset": int(tool_parameters.get("offset") or 0),
        }
        if tool_parameters.get("object_type"):
            params["object_type"] = tool_parameters["object_type"]
        if tool_parameters.get("status"):
            params["status"] = tool_parameters["status"]

        try:
            resp = pisces_request("GET", "/iocs", self.runtime.credentials, params=params)
        except PiscesError as e:
            yield self.create_text_message(f"请求失败: {e}")
            return

        if not resp.ok:
            yield self.create_text_message(
                f"查询 IOC 失败（{resp.status_code}）: {error_message(resp)}"
            )
            return

        data = resp.json()
        total = data.get("total", 0)
        iocs = data.get("data", [])
        yield self.create_text_message(f"共 {total} 条 IOC，本次返回 {len(iocs)} 条。")
        yield self.create_json_message(data)
