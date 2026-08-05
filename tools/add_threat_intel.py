from collections.abc import Generator
from typing import Any

from dify_plugin import Tool
from dify_plugin.entities.tool import ToolInvokeMessage

from provider.pisces import PiscesError, error_message, pisces_request

# Item fields passed through to the API untouched apart from emptiness checks.
_PASSTHROUGH = ("type", "actor", "malware", "phase", "ref_url", "evidence", "note")


def split_values(raw: Any) -> list[str]:
    """One or many IOC values into a clean list. Newlines always separate; commas do too,
    except inside a URL, whose query string may legitimately contain one."""
    if isinstance(raw, list):
        candidates = [str(v) for v in raw]
    else:
        candidates = str(raw or "").splitlines()

    values: list[str] = []
    for line in candidates:
        parts = [line] if "://" in line else line.split(",")
        for part in parts:
            cleaned = part.strip().strip('"').strip("'").rstrip(".,;")
            if cleaned and cleaned not in values:
                values.append(cleaned)
    return values


class AddThreatIntelTool(Tool):
    def _invoke(self, tool_parameters: dict[str, Any]) -> Generator[ToolInvokeMessage, None, None]:
        values = split_values(tool_parameters.get("value"))
        if not values:
            yield self.create_text_message("未提供有效的情报值（value）。")
            return

        source = str(tool_parameters.get("source") or "").strip()
        if not source:
            yield self.create_text_message("数据源（source）不能为空。")
            return

        item: dict[str, Any] = {}
        for field in _PASSTHROUGH:
            value = tool_parameters.get(field)
            if value is not None and str(value).strip():
                item[field] = str(value).strip()

        if tool_parameters.get("tlp"):
            item["tlp"] = tool_parameters["tlp"]
        if tool_parameters.get("confidence") is not None and str(tool_parameters["confidence"]).strip():
            item["confidence"] = int(tool_parameters["confidence"])
        if tool_parameters.get("expire_days"):
            item["expire_days"] = int(tool_parameters["expire_days"])

        tags = tool_parameters.get("tags")
        if isinstance(tags, list):
            tags = ",".join(str(t) for t in tags)
        tags = str(tags or "").strip()
        if tags:
            item["tags"] = tags

        # Every value shares the same metadata; the API takes them as one batch.
        body = {"source": source, "items": [dict(item, value=v) for v in values]}

        try:
            resp = pisces_request("POST", "/intel/indicators", self.runtime.credentials, json=body)
        except PiscesError as e:
            yield self.create_text_message(f"请求失败: {e}")
            return

        if not resp.ok:
            yield self.create_text_message(
                f"添加威胁情报失败（{resp.status_code}）: {error_message(resp)}"
            )
            return

        data = resp.json()
        counts = data.get("data") or {}
        created = counts.get("created", 0)
        merged = counts.get("merged", 0)
        skipped = counts.get("skipped", 0)

        summary = (
            f"已提交 {len(values)} 条威胁情报到数据源「{source}」："
            f"新建 {created} 条，合并到已有情报 {merged} 条，无法解析跳过 {skipped} 条。"
        )
        if skipped:
            summary += "（跳过通常是因为值不是可识别的 IP / 域名 / URL / MD5 / SHA256 / 邮箱）"
        yield self.create_text_message(summary)
        yield self.create_json_message(data)
