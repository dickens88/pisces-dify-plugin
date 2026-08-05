from collections.abc import Generator
from typing import Any
from urllib.parse import quote

from dify_plugin import Tool
from dify_plugin.entities.tool import ToolInvokeMessage

from provider.pisces import PiscesError, error_message, pisces_request

# How many candidates the keyword fallback pulls back before giving up on disambiguating.
SEARCH_LIMIT = 20


class QueryEntityProfileTool(Tool):
    def _get_json(self, path: str, params: dict = None, what: str = "实体画像"):
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

    def _invoke(self, tool_parameters: dict[str, Any]) -> Generator[ToolInvokeMessage, None, None]:
        object_name = tool_parameters.get("object_name")

        if object_name:
            yield from self._query_one(str(object_name))
            return

        # object_name omitted — list/search profiles instead, optionally filtered by monitoring state.
        monitoring = tool_parameters.get("monitoring")
        params: dict[str, Any] = {
            "limit": int(tool_parameters.get("limit") or 50),
            "offset": int(tool_parameters.get("offset") or 0),
        }
        if monitoring is not None:
            params["monitoring"] = "true" if bool(monitoring) else "false"
        # A switch, not a tri-state: the API filters on an exact security_tag value,
        # so "off" means no filter rather than "everything except attackers".
        if tool_parameters.get("attacker_only"):
            params["security_tag"] = "attack"

        data, err, _ = self._get_json("/entities", params=params, what="实体画像列表")
        if err:
            yield self.create_text_message(err)
            return

        total = data.get("total", 0)
        rows = data.get("data", [])
        scope = {"true": "已添加盯防的", "false": "未添加盯防的"}.get(params.get("monitoring"), "")
        if params.get("security_tag") == "attack":
            scope += "攻击者"
        yield self.create_text_message(f"{scope}实体画像共 {total} 条，本次返回 {len(rows)} 条。")
        yield self.create_json_message(data)

    def _query_one(self, object_name: str) -> Generator[ToolInvokeMessage, None, None]:
        """One entity's profile. Profiles are keyed by tenant name, so a domainid misses the
        exact lookup; fall back to keyword search, then re-fetch the detail it resolves to."""
        data, err, status = self._get_profile(object_name)
        if data is not None:
            yield self.create_text_message(f"已获取实体 {object_name} 的画像信息。")
            yield self.create_json_message(data)
            return
        if status != 404:
            yield self.create_text_message(err)
            return

        found, err, _ = self._search_profiles(object_name)
        if err:
            yield self.create_text_message(err)
            return

        rows = found.get("data") or []
        if not rows:
            yield self.create_text_message(f"未找到实体 {object_name} 的画像。")
            return
        if len(rows) > 1:
            names = "、".join(r.get("_id") for r in rows if r.get("_id"))
            yield self.create_text_message(
                f"{object_name} 匹配到 {found.get('total', len(rows))} 个实体：{names}。"
                "请用其中一个确切名称重新查询。"
            )
            yield self.create_json_message(found)
            return

        resolved = rows[0].get("_id")
        data, err, _ = self._get_profile(resolved)
        if err:
            yield self.create_text_message(err)
            return
        yield self.create_text_message(f"{object_name} 对应的实体是 {resolved}，已获取其画像信息。")
        yield self.create_json_message(data)
