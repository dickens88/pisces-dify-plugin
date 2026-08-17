from collections.abc import Generator
from typing import Any

from dify_plugin import Tool
from dify_plugin.entities.tool import ToolInvokeMessage

from provider.pisces import PiscesError, error_message, pisces_request

SEVERITIES = ("info", "success", "warning", "critical")
SEVERITY_LABELS = {"info": "提示", "success": "成功", "warning": "警告", "critical": "严重"}
# The server truncates a longer title itself; matching it here keeps the echo honest.
MAX_TITLE_LEN = 512
MAX_CATEGORY_LEN = 32


def split_recipients(raw: Any) -> list[str]:
    """One or many usernames / groups into a clean list. Newlines, English and Chinese
    commas, and semicolons all separate; duplicates and blanks are dropped."""
    if isinstance(raw, list):
        candidates = [str(v) for v in raw]
    else:
        candidates = str(raw or "").splitlines()

    names: list[str] = []
    for line in candidates:
        for separator in ("，", "；", ";"):
            line = line.replace(separator, ",")
        for part in line.split(","):
            cleaned = part.strip().strip('"').strip("'")
            if cleaned and cleaned not in names:
                names.append(cleaned)
    return names


class SendNotificationTool(Tool):
    def _invoke(self, tool_parameters: dict[str, Any]) -> Generator[ToolInvokeMessage, None, None]:
        title = str(tool_parameters.get("title") or "").strip()
        if not title:
            yield self.create_text_message("通知标题（title）不能为空。")
            return

        category = str(tool_parameters.get("category") or "").strip() or "智能体"
        if len(category) > MAX_CATEGORY_LEN:
            yield self.create_text_message(
                f"通知分类（category）最长 {MAX_CATEGORY_LEN} 个字符，当前 {len(category)} 个。"
            )
            return

        to_all = bool(tool_parameters.get("to_all"))
        to_users = split_recipients(tool_parameters.get("to_users"))
        to_groups = split_recipients(tool_parameters.get("to_groups"))
        if not to_all and not to_users and not to_groups:
            yield self.create_text_message(
                "没有收件人：请填写 to_users（用户名，多个用英文逗号分隔）或 to_groups（用户组），"
                "或把 to_all 设为 true 向全体用户发布。"
            )
            return
        # to_all covers everyone, so any named recipient is already included.
        if to_all:
            to_users, to_groups = [], []

        severity = str(tool_parameters.get("severity") or "info").strip().lower()
        if severity not in SEVERITIES:
            severity = "info"

        body: dict[str, Any] = {
            "category": category,
            "title": title[:MAX_TITLE_LEN],
            "severity": severity,
            "to": {"users": to_users, "groups": to_groups, "all": to_all},
        }
        for name in ("body", "link", "dedupe_key"):
            value = tool_parameters.get(name)
            if value is not None and str(value).strip():
                body[name] = str(value).strip()

        try:
            resp = pisces_request("POST", "/notifications", self.runtime.credentials, json=body)
        except PiscesError as e:
            yield self.create_text_message(f"请求失败: {e}")
            return

        if resp.status_code == 403:
            yield self.create_text_message(
                "发布失败（403）：当前凭据的账号没有群发权限，无法向用户组或全体用户发布通知"
                "（群发白名单由平台配置 application.notification.broadcast_senders 控制）。"
                "可以改为用 to_users 指定具体收件人。"
            )
            return
        if not resp.ok:
            yield self.create_text_message(
                f"发布通知失败（{resp.status_code}）: {error_message(resp)}"
            )
            return

        data = (resp.json() or {}).get("data") or {}
        if to_all:
            audience_text = "全体用户"
        else:
            parts = []
            if to_users:
                parts.append(f"用户 {'、'.join(to_users)}")
            if to_groups:
                parts.append(f"用户组 {'、'.join(to_groups)}")
            audience_text = "，".join(parts)

        yield self.create_text_message(
            f"已发布通知「{title}」到{audience_text}"
            f"（分类: {category}，级别: {SEVERITY_LABELS[severity]}）。"
        )
        yield self.create_json_message(
            {
                "notification_id": data.get("notification_id"),
                "audience": data.get("audience"),
                "category": category,
                "title": title,
                "severity": severity,
                "to_users": to_users,
                "to_groups": to_groups,
                "to_all": to_all,
                "sent": True,
            }
        )
