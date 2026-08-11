import json
from collections.abc import Generator
from typing import Any
from urllib.parse import quote

from dify_plugin import Tool
from dify_plugin.entities.tool import ToolInvokeMessage

from provider.pisces import PiscesError, error_message, pisces_request


def _parse_rows(raw: Any) -> tuple[list[dict], str]:
    """Read the rows parameter into a list of objects. Returns (rows, error message)."""
    if raw is None or (isinstance(raw, str) and not raw.strip()):
        return [], ""
    if isinstance(raw, list):
        parsed: Any = raw
    elif isinstance(raw, dict):
        parsed = [raw]
    else:
        try:
            parsed = json.loads(str(raw))
        except ValueError as e:
            return [], f"rows 不是合法的 JSON: {e}"
        if isinstance(parsed, dict):  # a single row handed over unwrapped
            parsed = [parsed]
    if not isinstance(parsed, list):
        return [], "rows 必须是 JSON 数组，数组里每个元素是一条命中记录（JSON 对象）。"
    # The server silently drops non-objects, which would quietly shrink the evidence.
    if any(not isinstance(row, dict) for row in parsed):
        return [], "rows 数组里每个元素都必须是 JSON 对象（键值对），不能是字符串或数字。"
    return parsed, ""


class HuntTaskCallbackTool(Tool):
    def _invoke(self, tool_parameters: dict[str, Any]) -> Generator[ToolInvokeMessage, None, None]:
        status = str(tool_parameters.get("status") or "").strip().lower()
        if status not in ("ok", "failed"):
            yield self.create_text_message("status 必须是 ok 或 failed。")
            return

        rows, rows_error = _parse_rows(tool_parameters.get("rows"))
        if rows_error:
            yield self.create_text_message(f"参数错误: {rows_error}")
            return

        body: dict[str, Any] = {"status": status, "rows": rows}

        path, path_error = self._callback_path(tool_parameters)
        if path_error:
            yield self.create_text_message(path_error)
            return

        try:
            resp = pisces_request("PUT", path, self.runtime.credentials, json=body)
        except PiscesError as e:
            yield self.create_text_message(f"请求失败: {e}")
            return

        if resp.status_code == 404:
            yield self.create_text_message(
                f"回调失败（404）：未找到该狩猎执行记录，请核对 hunt_id / run_id / task_id。"
                f" 服务端返回: {error_message(resp)}"
            )
            return
        if resp.status_code == 409:
            # A run that already finished — a duplicate callback, or one that arrived after the
            # run was force-closed as stale. Either way the result is not recorded.
            yield self.create_text_message(
                "回调失败（409）：该任务已不在等待结果（可能已回调过，或该次执行已结束），本次结果未被记录。"
            )
            return
        if not resp.ok:
            yield self.create_text_message(
                f"回调失败（{resp.status_code}）: {error_message(resp)}"
            )
            return

        task = (resp.json() or {}).get("data") or {}
        if status == "failed":
            yield self.create_text_message("已回调狩猎任务执行失败。")
        else:
            findings_count = task.get("findings", len(rows))
            yield self.create_text_message(
                f"已回调狩猎任务结果（状态: 成功，命中 {findings_count} 条，回传样本 {len(rows)} 条）。"
            )
        yield self.create_json_message(task)

    @staticmethod
    def _callback_path(tool_parameters: dict[str, Any]) -> tuple[str, str]:
        """The API path to PUT to. Returns (path, error message).

        Built from the hunt_id, run_id and task_id the workflow received in its inputs; the
        host to talk to is the one in the credentials, which is where the login token came from."""
        ids = {}
        for name in ("hunt_id", "run_id", "task_id"):
            value = str(tool_parameters.get(name) or "").strip()
            if not value:
                return "", f"缺少 {name}：请传入狩猎任务下发时随输入给出的 hunt_id、run_id、task_id。"
            ids[name] = value

        try:
            int(ids["task_id"])
        except ValueError:
            return "", f"task_id 必须是整数，收到: {ids['task_id']}"

        return (f"/hunting/hunts/{quote(ids['hunt_id'], safe='')}"
                f"/runs/{quote(ids['run_id'], safe='')}/tasks/{ids['task_id']}/result"), ""
