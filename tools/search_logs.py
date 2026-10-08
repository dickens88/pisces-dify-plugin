from collections.abc import Generator
from datetime import datetime, timedelta, timezone
from typing import Any

from dify_plugin import Tool
from dify_plugin.entities.tool import ToolInvokeMessage

from provider.pisces import PiscesError, error_message, pisces_request

# The server caps a page at application.threat_hunting.max_rows (500 by default).
MAX_SIZE = 500
# Relative windows offered in the form; the server needs ISO bounds, so they resolve here.
TIME_RANGES = {
    "15m": timedelta(minutes=15),
    "1h": timedelta(hours=1),
    "4h": timedelta(hours=4),
    "24h": timedelta(hours=24),
    "7d": timedelta(days=7),
    "30d": timedelta(days=30),
}


class SearchLogsTool(Tool):
    @staticmethod
    def _window(tool_parameters: dict[str, Any]) -> tuple[str, str]:
        """Explicit start_time/end_time win; otherwise time_range back from end (or now)."""
        start = str(tool_parameters.get("start_time") or "").strip()
        end = str(tool_parameters.get("end_time") or "").strip()
        if start:
            return start, end or datetime.now(timezone.utc).isoformat()
        span = TIME_RANGES.get(str(tool_parameters.get("time_range") or "24h"), TIME_RANGES["24h"])
        anchor = datetime.fromisoformat(end.replace("Z", "+00:00")) if end else datetime.now(timezone.utc)
        return (anchor - span).isoformat(), anchor.isoformat()

    def _invoke(self, tool_parameters: dict[str, Any]) -> Generator[ToolInvokeMessage, None, None]:
        spl = str(tool_parameters.get("spl") or "").strip()
        index_pattern = str(tool_parameters.get("index_pattern") or "").strip()
        if not spl:
            yield self.create_text_message("SPL 查询语句不能为空。")
            return
        if not index_pattern:
            yield self.create_text_message("索引模式（index_pattern）不能为空。")
            return

        try:
            start_time, end_time = self._window(tool_parameters)
        except ValueError:
            yield self.create_text_message("end_time 不是合法的 ISO 8601 时间，例如 2026-07-01T00:00:00Z。")
            return

        size = tool_parameters.get("size")
        payload = {
            "query": spl,
            "language": "spl",
            "index_pattern": index_pattern,
            "start_time": start_time,
            "end_time": end_time,
            "offset": int(tool_parameters.get("offset") or 0),
            # size 0 is a real ask (totals only), so `or` would eat it.
            "size": max(0, min(int(size), MAX_SIZE)) if size is not None else 100,
            "exact_total": bool(tool_parameters.get("exact_total")),
        }

        try:
            resp = pisces_request("POST", "/hunting/searches", self.runtime.credentials,
                                  json=payload, timeout=60)
        except PiscesError as e:
            yield self.create_text_message(f"请求失败: {e}")
            return

        if not resp.ok:
            yield self.create_text_message(f"日志检索失败（{resp.status_code}）: {error_message(resp)}")
            return

        data = resp.json().get("data") or {}
        rows = data.get("rows") or []
        yield self.create_text_message(
            f"日志检索完成：命中 {data.get('total', 0)} 条，本次返回 {len(rows)} 条，"
            f"耗时 {data.get('took_ms', 0)} ms（{data.get('start_time')} ~ {data.get('end_time')}）。"
        )
        yield self.create_json_message({
            "view": data.get("view"),
            "columns": data.get("columns") or [],
            "rows": rows,
            "total": data.get("total", 0),
            "took_ms": data.get("took_ms", 0),
            "start_time": data.get("start_time"),
            "end_time": data.get("end_time"),
        })
