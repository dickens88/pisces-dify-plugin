from collections.abc import Generator
from datetime import datetime, timedelta, timezone
from typing import Any

from dify_plugin import Tool
from dify_plugin.entities.tool import ToolInvokeMessage

from provider.pisces import PiscesError, error_message, pisces_request


def _csv(value: Any) -> str:
    """Normalize a comma/semicolon/whitespace separated list into a clean CSV string."""
    if isinstance(value, list):
        items = [str(v).strip() for v in value]
    else:
        items = [v.strip() for v in str(value or "").replace(";", ",").split(",")]
    return ",".join(i for i in items if i)


class QueryThreatIntelTool(Tool):
    def _invoke(self, tool_parameters: dict[str, Any]) -> Generator[ToolInvokeMessage, None, None]:
        page = max(1, int(tool_parameters.get("page") or 1))
        limit = max(1, min(int(tool_parameters.get("limit") or 50), 500))

        params: dict[str, Any] = {"page": page, "limit": limit}

        feed = _csv(tool_parameters.get("feed"))
        if feed:
            params["feed"] = feed
        tag = _csv(tool_parameters.get("tag"))
        if tag:
            params["tag"] = tag

        # start_time/end_time filter on last_seen (最近更新时间). Explicit bounds win
        # over `days`, which is the convenience form for "最近 N 天更新过的情报".
        start_time = (tool_parameters.get("start_time") or "").strip()
        end_time = (tool_parameters.get("end_time") or "").strip()
        days = tool_parameters.get("days")
        if not start_time and days:
            start_time = (datetime.now(timezone.utc) - timedelta(days=int(days))).strftime(
                "%Y-%m-%dT%H:%M:%S.000Z"
            )
        if start_time:
            params["start_time"] = start_time
        if end_time:
            params["end_time"] = end_time

        try:
            resp = pisces_request("GET", "/intel/indicators", self.runtime.credentials, params=params)
        except PiscesError as e:
            yield self.create_text_message(f"请求失败: {e}")
            return

        if not resp.ok:
            yield self.create_text_message(
                f"查询威胁情报失败（{resp.status_code}）: {error_message(resp)}"
            )
            return

        data = resp.json()
        total = data.get("total", 0)
        rows = data.get("data", [])

        conditions = []
        if feed:
            conditions.append(f"数据源={feed}")
        if tag:
            conditions.append(f"标签={tag}")
        if start_time:
            conditions.append(f"更新时间≥{start_time}")
        if end_time:
            conditions.append(f"更新时间≤{end_time}")
        scope = "、".join(conditions) if conditions else "全部情报"

        yield self.create_text_message(
            f"威胁情报查询（{scope}）：共 {total} 条，第 {page} 页返回 {len(rows)} 条。"
        )
        yield self.create_json_message(data)
