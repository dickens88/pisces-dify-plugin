from collections.abc import Generator
from datetime import datetime, timedelta, timezone
from typing import Any

import requests
import urllib3
from dify_plugin import Tool
from dify_plugin.entities.tool import ToolInvokeMessage

urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

from provider.pisces import get_token


def _parse_date(value: Any):
    if not value:
        return None
    try:
        return datetime.strptime(str(value)[:10], "%Y-%m-%d").date()
    except (ValueError, TypeError):
        return None


ROLE_LABELS = {"manager": "值班经理", "tracer": "溯源专员"}


def _role_label(role: Any) -> str:
    return ROLE_LABELS.get(role, role or "值班经理")


class QueryShiftManagersTool(Tool):
    def _invoke(self, tool_parameters: dict[str, Any]) -> Generator[ToolInvokeMessage, None, None]:
        base_url = self.runtime.credentials["base_url"].rstrip("/")
        username = self.runtime.credentials["username"]
        password = self.runtime.credentials["password"]

        try:
            token = get_token(base_url, username, password)
        except Exception as e:
            yield self.create_text_message(f"登录失败: {e}")
            return

        headers = {"Authorization": f"Bearer {token}"}
        url = f"{base_url}/shift-manager/roster"

        current_only = bool(tool_parameters.get("current_only"))

        # ── current duty shifts for both roles (the shifts covering "now") ──
        if current_only:
            try:
                resp = requests.get(
                    url,
                    params={"action": "current_shift"},
                    headers=headers,
                    timeout=30,
                    verify=False,
                )
            except requests.exceptions.RequestException as e:
                yield self.create_text_message(f"请求失败: {e}")
                return

            if not resp.ok:
                body = resp.json() if resp.content else {}
                msg = body.get("error_message") or resp.text
                yield self.create_text_message(f"查询当前值班人员失败（{resp.status_code}）: {msg}")
                return

            data = resp.json()
            shifts = data.get("data") or []
            if not shifts:
                yield self.create_text_message("当前没有匹配的值班排班。")
            else:
                lines = [
                    f"当前{_role_label(shift.get('role'))}：{shift.get('manager_user') or '未指定'}"
                    f"（备份：{shift.get('backup_user') or '无'}，"
                    f"值班周期 {shift.get('period_start')} ~ {shift.get('period_end')}）"
                    for shift in shifts
                ]
                yield self.create_text_message("；".join(lines) + "。")
            yield self.create_json_message(data)
            return

        # ── roster list within the time range (past N days) ──────────────────
        days = int(tool_parameters.get("days") or 30)
        today = datetime.now(timezone.utc).date()
        win_start = today - timedelta(days=days)
        win_end = today

        try:
            resp = requests.get(
                url,
                params={"limit": 1000, "offset": 0},
                headers=headers,
                timeout=30,
                verify=False,
            )
        except requests.exceptions.RequestException as e:
            yield self.create_text_message(f"请求失败: {e}")
            return

        if not resp.ok:
            body = resp.json() if resp.content else {}
            msg = body.get("error_message") or resp.text
            yield self.create_text_message(f"查询排班清单失败（{resp.status_code}）: {msg}")
            return

        data = resp.json()
        rosters = data.get("data", [])

        # The roster endpoint has no server-side time filter, so keep only the
        # rosters whose duty period overlaps the requested [win_start, win_end] window.
        filtered = []
        for r in rosters:
            ps = _parse_date(r.get("period_start"))
            pe = _parse_date(r.get("period_end"))
            if ps and pe and ps <= win_end and pe >= win_start:
                filtered.append(r)

        counts: dict[str, int] = {}
        for r in filtered:
            key = r.get("role") or "manager"
            counts[key] = counts.get(key, 0) + 1
        breakdown = "，".join(f"{_role_label(k)} {v} 条" for k, v in counts.items())
        summary = f"共 {len(filtered)} 条排班" + (f"（{breakdown}）" if breakdown else "")

        yield self.create_text_message(
            f"近 {days} 天（{win_start} ~ {win_end}）排班清单：{summary}。"
        )
        yield self.create_json_message(
            {
                "data": filtered,
                "total": len(filtered),
                "time_from": win_start.isoformat(),
                "time_to": win_end.isoformat(),
            }
        )
