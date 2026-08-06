from collections.abc import Generator
from typing import Any
from urllib.parse import quote

from dify_plugin import Tool
from dify_plugin.entities.tool import ToolInvokeMessage

from provider.pisces import PiscesError, error_message, pisces_request


class AddMonitoringTool(Tool):
    def _invoke(self, tool_parameters: dict[str, Any]) -> Generator[ToolInvokeMessage, None, None]:
        object_name = tool_parameters["object_name"]
        # monitoring defaults to enabling the tag; pass false to remove it.
        enable = tool_parameters.get("enable")
        enable = True if enable is None else bool(enable)

        tenant_tags: dict[str, Any] = {"monitoring": enable}
        remark = tool_parameters.get("remark")
        if remark is not None and str(remark).strip() != "":
            tenant_tags["remark"] = remark

        body = {"tenant_tags": tenant_tags}
        path = f"/entities/{quote(str(object_name), safe='')}"
        try:
            resp = pisces_request("PATCH", path, self.runtime.credentials, json=body)
        except PiscesError as e:
            yield self.create_text_message(f"请求失败: {e}")
            return

        if not resp.ok:
            action = "添加盯防" if enable else "取消盯防"
            yield self.create_text_message(
                f"{action}失败（{resp.status_code}）: {error_message(resp)}"
            )
            return

        # The response body is deliberately not read — see update_entity_profile.
        action = "已添加盯防标记" if enable else "已取消盯防标记"
        yield self.create_text_message(f"{action}: {object_name}")
        yield self.create_json_message(
            {"object_name": object_name, "monitoring": enable, "updated": True}
        )
