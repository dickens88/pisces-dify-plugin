import json
import re
from collections.abc import Generator
from typing import Any

from dify_plugin import Tool
from dify_plugin.entities.tool import ToolInvokeMessage

from provider.pisces import PiscesError, error_message, pisces_request

# tag_mode → request body key on PUT /shift-manager/reviews action=update.
_TAG_KEYS = {"replace": "tags", "add": "add_tags", "remove": "remove_tags"}


def _parse_tags(raw: Any) -> list | None:
    """Accept a JSON array or comma / 、 / newline separated text; None when malformed."""
    if isinstance(raw, list):
        items = raw
    else:
        text = str(raw).strip()
        if text.startswith("{"):
            return None
        if text.startswith("["):
            try:
                items = json.loads(text)
            except json.JSONDecodeError:
                return None
            if not isinstance(items, list):
                return None
        else:
            items = re.split(r"[,，、;；\n]", text)
    if not all(isinstance(x, str) for x in items):
        return None
    return [x.strip() for x in items if x.strip()]


class UpdateReviewTool(Tool):
    def _invoke(self, tool_parameters: dict[str, Any]) -> Generator[ToolInvokeMessage, None, None]:
        alert_id = str(tool_parameters.get("alert_id") or "").strip()
        if not alert_id:
            yield self.create_text_message("缺少告警 ID（alert_id）。")
            return

        body: dict[str, Any] = {"action": "update", "alert_id": alert_id}

        tags = tool_parameters.get("tags")
        if tags is not None and str(tags).strip():
            parsed = _parse_tags(tags)
            if parsed is None:
                yield self.create_text_message(
                    '标签（tags）格式不正确：请传 JSON 字符串数组（如 ["误报", "已加白"]）或用逗号分隔的文本。'
                )
                return
            mode = str(tool_parameters.get("tag_mode") or "replace").strip()
            if mode not in _TAG_KEYS:
                yield self.create_text_message(f"不支持的标签修改方式: {mode}")
                return
            if not parsed and mode != "replace":
                yield self.create_text_message("没有可追加或删除的标签。")
                return
            body[_TAG_KEYS[mode]] = parsed

        comment = tool_parameters.get("comment")
        if comment is not None and str(comment).strip():
            body["comment"] = str(comment)

        if len(body) == 2:
            yield self.create_text_message("未提供任何要修改的字段（tags / comment）。")
            return

        try:
            resp = pisces_request("PUT", "/shift-manager/reviews", self.runtime.credentials, json=body)
        except PiscesError as e:
            yield self.create_text_message(f"请求失败: {e}")
            return

        if resp.status_code == 404:
            yield self.create_text_message(f"复核队列中没有告警 {alert_id} 的记录。")
            return
        if not resp.ok:
            yield self.create_text_message(f"修改复核记录失败（{resp.status_code}）: {error_message(resp)}")
            return

        row = (resp.json() or {}).get("data") or {}
        tag_text = "、".join(row.get("tags") or []) or "无"
        yield self.create_text_message(f"已修改告警 {alert_id} 的复核记录，当前标签：{tag_text}。")
        yield self.create_json_message(row)
