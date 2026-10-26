from collections.abc import Generator
from typing import Any
from urllib.parse import quote

from dify_plugin import Tool
from dify_plugin.entities.tool import ToolInvokeMessage

from provider.pisces import PiscesError, error_message, pisces_request

CATEGORY_LABELS = {"comments": "人工评论", "intelligence": "情报", "ai": "AI 研判", "historic": "历史参考"}


class QueryCommentsTool(Tool):
    def _invoke(self, tool_parameters: dict[str, Any]) -> Generator[ToolInvokeMessage, None, None]:
        event_id = str(tool_parameters["event_id"]).strip()
        params: dict[str, Any] = {
            "limit": int(tool_parameters.get("limit") or 200),
            "offset": int(tool_parameters.get("offset") or 0),
        }
        if tool_parameters.get("workspace"):
            params["workspace"] = tool_parameters["workspace"]

        try:
            resp = pisces_request("GET", f"/comments/{quote(event_id, safe='')}", self.runtime.credentials,
                                  params=params)
        except PiscesError as e:
            yield self.create_text_message(f"请求失败: {e}")
            return

        if not resp.ok:
            yield self.create_text_message(
                f"查询评论失败（{resp.status_code}）: {error_message(resp)}"
            )
            return

        data = resp.json()
        groups = data.get("data") or {}
        breakdown = "，".join(f"{label} {len(groups.get(key) or [])} 条" for key, label in CATEGORY_LABELS.items())
        yield self.create_text_message(f"共 {data.get('total', 0)} 条笔记，本页：{breakdown}。")
        yield self.create_json_message(data)
