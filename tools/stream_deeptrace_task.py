import json
import time
from collections.abc import Generator
from typing import Any

import requests
import urllib3
from dify_plugin import Tool
from dify_plugin.entities.tool import ToolInvokeMessage

urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

from provider.pisces import get_token


class StreamDeeptraceTaskTool(Tool):
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
        timeout = int(tool_parameters.get("timeout") or 120)
        url = f"{base_url}/deeptrace/sessions/{session_id}/stream"

        # Consume SSE stream with a hard timeout
        text_parts: list[str] = []
        events: list[dict] = []
        deadline = time.monotonic() + timeout

        try:
            resp = requests.get(
                url,
                headers={"Authorization": f"Bearer {token}"},
                stream=True,
                timeout=(10, timeout + 5),
                verify=False,
            )
        except requests.exceptions.RequestException as e:
            yield self.create_text_message(f"连接 SSE 流失败: {e}")
            return

        if not resp.ok:
            body = resp.json() if resp.content else {}
            msg = body.get("error_message") or body.get("error") or resp.text
            yield self.create_text_message(f"获取流失败（{resp.status_code}）: {msg}")
            return

        # Parse SSE: lines like "event: <type>", "id: <seq>", "data: <json>", blank line = end of event
        current_event = ""
        current_data_lines: list[str] = []

        def _flush_event():
            nonlocal current_event, current_data_lines
            if not current_event:
                current_event = "message"
            raw_data = "\n".join(current_data_lines)
            try:
                payload = json.loads(raw_data)
            except (json.JSONDecodeError, TypeError):
                payload = {"raw": raw_data}

            events.append({"event": current_event, "data": payload})

            # Extract text content from common event types
            if current_event in ("chunk", "text", "assistant", "result"):
                content = payload.get("content") or payload.get("text") or ""
                if content:
                    text_parts.append(content)
            elif current_event == "error":
                text_parts.append(f"[ERROR] {payload.get('error', raw_data)}")

            current_event = ""
            current_data_lines = []

        try:
            for line in resp.iter_lines(decode_unicode=True):
                if time.monotonic() >= deadline:
                    break

                if line is None:
                    continue

                if line == "":
                    # End of event block
                    if current_event or current_data_lines:
                        _flush_event()
                    continue

                if line.startswith("event: "):
                    current_event = line[7:]
                elif line.startswith("id: "):
                    pass  # track seq if needed
                elif line.startswith("data: "):
                    current_data_lines.append(line[6:])
                elif line.startswith(": "):
                    pass  # SSE comment, ignore
                else:
                    current_data_lines.append(line)

                # Early exit on "done" event
                if current_event == "done":
                    _flush_event()
                    break
        finally:
            resp.close()

        # Flush any trailing partial event
        if current_event or current_data_lines:
            _flush_event()

        full_text = "".join(text_parts)
        summary = f"共收到 {len(events)} 个事件"
        if full_text:
            summary += f"，文本输出 {len(full_text)} 字符"
        yield self.create_text_message(summary)
        if full_text:
            yield self.create_text_message(full_text)
        yield self.create_json_message({"session_id": session_id, "events": events, "text": full_text})
