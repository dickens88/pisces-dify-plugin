from collections.abc import Generator
from typing import Any
from urllib.parse import quote

from dify_plugin import Tool
from dify_plugin.entities.tool import ToolInvokeMessage

from provider.pisces import PiscesError, error_message, pisces_request

# How many candidates the keyword fallback pulls back before giving up on disambiguating.
SEARCH_LIMIT = 20
# Batch export: page size used while paging through every match, and the hard cap on how
# many rows one export call will ever return (a runaway filter should not hang the tool).
EXPORT_PAGE_SIZE = 100
EXPORT_MAX_ROWS = 2000

TRACE_STATUS_LABELS = {"running": "溯源中", "complete": "已完成", None: "未溯源"}
AI_FEEDBACK_LABELS = {"up": "准确", "down": "不准确"}


class QueryTraceResultTool(Tool):
    def _get_json(self, path: str, params: dict = None, what: str = "溯源结果"):
        """GET `path`, returning (data, error_message, status_code). data is None on any failure."""
        try:
            resp = pisces_request("GET", path, self.runtime.credentials, params=params)
        except PiscesError as e:
            return None, f"请求失败: {e}", 0
        if not resp.ok:
            err = f"查询{what}失败（{resp.status_code}）: {error_message(resp)}"
            return None, err, resp.status_code
        return resp.json(), None, resp.status_code

    def _get_profile(self, object_name: str):
        """GET /entities/<object_name> — the full profile, matched on the exact object name."""
        return self._get_json(f"/entities/{quote(str(object_name), safe='')}")

    def _search_profiles(self, keyword: str):
        """GET /entities?action=list&q=... — the keyword search behind the console's search box.
        It matches basic.domainid and the user tags as well as the entity name itself."""
        return self._get_json("/entities",
                              params={"q": keyword, "limit": SEARCH_LIMIT, "offset": 0},
                              what="实体画像列表")

    @staticmethod
    def _extract(profile: dict, fallback_name: str) -> dict:
        """The attacker-trace subset of a profile: trace_status plus every trace_result field."""
        basic = profile.get("basic") or {}
        tags = profile.get("tenant_tags") or {}
        trace_result = tags.get("trace_result") or {}
        status = tags.get("trace_status")
        return {
            "object_name": profile.get("_id") or fallback_name,
            "domainid": basic.get("domainid") or profile.get("domainid") or "",
            "domainname": basic.get("domainname") or "",
            "trace_status": status,
            "trace_status_label": TRACE_STATUS_LABELS.get(status, status),
            "clue": trace_result.get("clue") or "",
            "start_user": trace_result.get("start_user") or "",
            "start_time": trace_result.get("start_time") or "",
            "refer_alert_id": trace_result.get("refer_alert_id") or "",
            "conclusion": trace_result.get("conclusion") or "",
            "ai_conclusion": trace_result.get("ai_result_raw") or "",
            "ai_feedback": trace_result.get("ai_feedback") or "",
            "update_user": trace_result.get("update_user") or "",
            "update_time": trace_result.get("update_time") or "",
        }

    @staticmethod
    def _summarize(row: dict) -> str:
        lines = [
            f"租户: {row['object_name']}" + (f"（{row['domainid']}）" if row["domainid"] else ""),
            f"溯源状态: {row['trace_status_label']}",
        ]
        if row["trace_status"]:
            lines.append(f"溯源线索: {row['clue'] or '-'}")
            lines.append(f"发起人员: {row['start_user'] or '-'}")
            if row["start_time"]:
                lines.append(f"发起时间: {row['start_time']}")
            if row["refer_alert_id"]:
                lines.append(f"发起来源: {row['refer_alert_id']}")
            if row["trace_status"] == "complete":
                lines.append(f"溯源结论: {row['conclusion'] or '-'}")
                if row["ai_conclusion"]:
                    lines.append(f"AI溯源结论: {row['ai_conclusion']}")
                if row["ai_feedback"]:
                    lines.append(f"AI结论评价: {AI_FEEDBACK_LABELS.get(row['ai_feedback'], row['ai_feedback'])}")
                lines.append(f"提交人员: {row['update_user'] or '-'}")
                if row["update_time"]:
                    lines.append(f"提交时间: {row['update_time']}")
        return "\n".join(lines)

    def _invoke(self, tool_parameters: dict[str, Any]) -> Generator[ToolInvokeMessage, None, None]:
        object_name = tool_parameters.get("object_name")
        if object_name:
            yield from self._query_one(str(object_name))
            return
        yield from self._export(tool_parameters)

    def _query_one(self, object_name: str) -> Generator[ToolInvokeMessage, None, None]:
        """One tenant's trace result. Profiles are keyed by tenant name, so a domainid or a
        partial name misses the exact lookup; fall back to keyword search like
        query_entity_profile does, then re-fetch the detail it resolves to."""
        data, err, status = self._get_profile(object_name)
        if data is None:
            if status != 404:
                yield self.create_text_message(err)
                return

            found, err, _ = self._search_profiles(object_name)
            if err:
                yield self.create_text_message(err)
                return

            rows = found.get("data") or []
            if not rows:
                yield self.create_text_message(f"未找到租户 {object_name}。")
                return
            if len(rows) > 1:
                names = "、".join(r.get("_id") for r in rows if r.get("_id"))
                yield self.create_text_message(
                    f"{object_name} 匹配到 {found.get('total', len(rows))} 个租户：{names}。"
                    "请用其中一个确切名称重新查询。"
                )
                yield self.create_json_message(found)
                return

            resolved = rows[0].get("_id")
            data, err, _ = self._get_profile(resolved)
            if err:
                yield self.create_text_message(err)
                return
            object_name = resolved

        profile = data.get("data") or {}
        row = self._extract(profile, object_name)
        if not row["trace_status"]:
            yield self.create_text_message(f"租户 {row['object_name']} 暂无溯源记录。")
        else:
            yield self.create_text_message(self._summarize(row))
        yield self.create_json_message(row)

    def _list_page(self, trace_status: str, limit: int, offset: int):
        """One page of GET /entities?action=list&trace_status=... — see entity_service.list_entities.
        trace_status is comma-separated among running/complete/none (absent), or 'all' for no filter."""
        params: dict[str, Any] = {"limit": limit, "offset": offset}
        if trace_status and trace_status != "all":
            params["trace_status"] = trace_status
        data, err, _ = self._get_json("/entities", params=params, what="溯源结果列表")
        if err:
            return None, None, err
        rows = [self._extract(r, r.get("_id")) for r in (data.get("data") or [])]
        return rows, data.get("total", 0), None

    def _export(self, tool_parameters: dict[str, Any]) -> Generator[ToolInvokeMessage, None, None]:
        trace_status = str(tool_parameters.get("trace_status") or "running,complete").strip()
        export_all = bool(tool_parameters.get("export_all"))

        if not export_all:
            limit = int(tool_parameters.get("limit") or 50)
            offset = int(tool_parameters.get("offset") or 0)
            rows, total, err = self._list_page(trace_status, limit, offset)
            if err:
                yield self.create_text_message(err)
                return
            yield self.create_text_message(
                f"符合条件的溯源结果共 {total} 条，本次返回 {len(rows)} 条（offset={offset}）。"
                "如需导出全部，请设置 export_all=true。"
            )
            yield self.create_json_message({"data": rows, "total": total})
            return

        # export_all: page through every match, up to EXPORT_MAX_ROWS as a safety cap.
        all_rows: list[dict] = []
        offset = 0
        total = 0
        while len(all_rows) < EXPORT_MAX_ROWS:
            rows, total, err = self._list_page(trace_status, EXPORT_PAGE_SIZE, offset)
            if err:
                yield self.create_text_message(err)
                return
            all_rows.extend(rows)
            offset += EXPORT_PAGE_SIZE
            if not rows or offset >= total:
                break

        truncated = total > len(all_rows)
        note = f"（已达到单次导出上限 {EXPORT_MAX_ROWS} 条，剩余请缩小 trace_status 范围分批导出）" if truncated else ""
        yield self.create_text_message(f"已导出溯源结果 {len(all_rows)}/{total} 条{note}。")
        yield self.create_json_message({"data": all_rows, "total": total, "truncated": truncated})
