from collections.abc import Generator
from typing import Any
from urllib.parse import quote

import requests
import urllib3
from dify_plugin import Tool
from dify_plugin.entities.tool import ToolInvokeMessage

urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

from provider.pisces import get_token

# Streaming deltas (assistant_chunk/thinking_chunk) are never persisted, so the
# stored assistant messages are the finalized answers.
ANSWER_KIND = "assistant"


class GetDeeptraceResultTool(Tool):
    def _invoke(self, tool_parameters: dict[str, Any]) -> Generator[ToolInvokeMessage, None, None]:
        base_url = self.runtime.credentials["base_url"].rstrip("/")
        username = self.runtime.credentials["username"]
        password = self.runtime.credentials["password"]

        try:
            token = get_token(base_url, username, password)
        except Exception as e:
            yield self.create_text_message(f"登录失败: {e}")
            return

        session_id = tool_parameters["session_id"]
        url = f"{base_url}/deeptrace/sessions/{quote(str(session_id), safe='')}/messages"
        try:
            resp = requests.get(
                url,
                headers={"Authorization": f"Bearer {token}"},
                timeout=60,
                verify=False,
            )
        except requests.exceptions.RequestException as e:
            yield self.create_text_message(f"请求失败: {e}")
            return

        if resp.status_code == 404:
            yield self.create_text_message(f"未找到Deeptrace会话 {session_id}。")
            return
        if not resp.ok:
            body = resp.json() if resp.content else {}
            msg = body.get("error_message") or body.get("error") or resp.text
            yield self.create_text_message(f"获取Deeptrace结果失败（{resp.status_code}）: {msg}")
            return

        messages = (resp.json() or {}).get("data") or []
        answers = [
            str(m.get("content") or "").strip()
            for m in messages
            if m.get("kind") == ANSWER_KIND and str(m.get("content") or "").strip()
        ]

        if not answers:
            yield self.create_text_message(
                f"会话 {session_id} 共 {len(messages)} 条消息，暂无分析结论"
                "（任务可能仍在运行，可用查询Deeptrace任务状态工具确认）。"
            )
            yield self.create_json_message(
                {"session_id": session_id, "result": "", "answers": [], "messages": messages}
            )
            return

        # 只返回最终结论时取最后一条，否则拼接全部回复。
        latest_only = tool_parameters.get("latest_only")
        latest_only = True if latest_only is None else bool(latest_only)
        result = answers[-1] if latest_only else "\n\n".join(answers)

        yield self.create_text_message(result)
        yield self.create_json_message({
            "session_id": session_id,
            "result": result,
            "answers": answers,
            "message_count": len(messages),
            "messages": messages,
        })
