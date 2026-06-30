from collections.abc import Generator
from datetime import datetime, timedelta, timezone
from typing import Any

import requests
import urllib3
from dify_plugin import Tool
from dify_plugin.entities.tool import ToolInvokeMessage

urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

from provider.pisces import get_token


class QueryReviewQueueTool(Tool):
    def _invoke(self, tool_parameters: dict[str, Any]) -> Generator[ToolInvokeMessage, None, None]:
        base_url = self.runtime.credentials["base_url"].rstrip("/")
        username = self.runtime.credentials["username"]
        password = self.runtime.credentials["password"]

        try:
            token = get_token(base_url, username, password)
        except Exception as e:
            yield self.create_text_message(f"登录失败: {e}")
            return

        days = int(tool_parameters.get("days") or 7)
        now = datetime.now(timezone.utc)
        time_from = (now - timedelta(days=days)).strftime("%Y-%m-%dT%H:%M:%S.000Z")
        time_to = now.strftime("%Y-%m-%dT%H:%M:%S.000Z")

        pending_only = bool(tool_parameters.get("pending_only"))

        payload: dict[str, Any] = {
            "action": "list",
            "time_from": time_from,
            "time_to": time_to,
            "limit": int(tool_parameters.get("limit") or 100),
            "offset": int(tool_parameters.get("offset") or 0),
        }
        if pending_only:
            # status="pending" keeps only alerts that have not been reviewed yet.
            payload["status"] = "pending"

        url = f"{base_url}/shift-manager/reviews"
        try:
            resp = requests.post(
                url,
                json=payload,
                headers={"Authorization": f"Bearer {token}"},
                timeout=30,
                verify=False,
            )
        except requests.exceptions.RequestException as e:
            yield self.create_text_message(f"请求失败: {e}")
            return

        if not resp.ok:
            body = resp.json() if resp.content else {}
            msg = body.get("error_message") or resp.text
            yield self.create_text_message(f"查询待复核告警失败（{resp.status_code}）: {msg}")
            return

        data = resp.json()
        total = data.get("total", 0)
        rows = data.get("data", [])
        scope = "待复核（未复核）" if pending_only else "全部"
        yield self.create_text_message(
            f"近 {days} 天{scope}告警复核清单：共 {total} 条，本次返回 {len(rows)} 条。"
        )
        yield self.create_json_message(data)
