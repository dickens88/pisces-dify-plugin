from collections.abc import Generator
from typing import Any

from dify_plugin import Tool
from dify_plugin.entities.tool import ToolInvokeMessage

from provider.pisces import PiscesError, error_message, pisces_request

# Both tuples mirror models/notification.py on the server; keep them in step.
TYPES = ("incident", "vuln", "tenant", "intel", "quality", "hunt", "approval", "assign", "notice")
TYPE_LABELS = {
    "incident": "安全事件", "vuln": "漏扫事件", "tenant": "恶意租户", "intel": "情报",
    "quality": "运营质量", "hunt": "狩猎结果", "approval": "审批请求", "assign": "指派与协作",
    "notice": "平台公告",
}
LEVELS = ("fatal", "high", "medium", "low", "tips")
LEVEL_LABELS = {"fatal": "致命", "high": "高", "medium": "中", "low": "低", "tips": "提示"}
TARGET_KINDS = ("host", "account", "ip", "domain", "tenant", "ds", "none")
# The server truncates title/target/tags itself; link and dedupe_key it does not, so we refuse them.
MAX_TITLE_LEN = 512
MAX_SOURCE_MODULE_LEN = 64
MAX_LINK_LEN = 512
MAX_TARGET_LEN = 255
MAX_DEDUPE_KEY_LEN = 128
MAX_TAG_LEN = 32
MAX_TAGS = 8


def split_list(raw: Any) -> list[str]:
    """One or many values into a clean list. Newlines, English and Chinese commas,
    and semicolons all separate; duplicates and blanks are dropped."""
    if isinstance(raw, list):
        candidates = [str(v) for v in raw]
    else:
        candidates = str(raw or "").splitlines()

    values: list[str] = []
    for line in candidates:
        for separator in ("，", "；", ";"):
            line = line.replace(separator, ",")
        for part in line.split(","):
            cleaned = part.strip().strip('"').strip("'")
            if cleaned and cleaned not in values:
                values.append(cleaned)
    return values


class SendNotificationTool(Tool):
    def _invoke(self, tool_parameters: dict[str, Any]) -> Generator[ToolInvokeMessage, None, None]:
        title = str(tool_parameters.get("title") or "").strip()
        if not title:
            yield self.create_text_message("通知标题（title）不能为空。")
            return

        msg_type = str(tool_parameters.get("type") or "").strip().lower()
        if msg_type not in TYPES:
            yield self.create_text_message(
                f"消息类型（type）无效：{msg_type or '空'}，可选值 {'、'.join(TYPES)}。"
            )
            return

        to_all = bool(tool_parameters.get("to_all"))
        to_users = split_list(tool_parameters.get("to_users"))
        to_groups = split_list(tool_parameters.get("to_groups"))
        if not to_all and not to_users and not to_groups:
            yield self.create_text_message(
                "没有收件人：请填写 to_users（用户名，多个用英文逗号分隔）或 to_groups（用户组），"
                "或把 to_all 设为 true 向全体用户发布。"
            )
            return
        # to_all covers everyone, so any named recipient is already included.
        if to_all:
            to_users, to_groups = [], []

        level = str(tool_parameters.get("level") or "tips").strip().lower()
        if level not in LEVELS:
            level = "tips"

        target = str(tool_parameters.get("target") or "").strip()[:MAX_TARGET_LEN]
        target_kind = str(tool_parameters.get("target_kind") or "none").strip().lower()
        if target_kind not in TARGET_KINDS or not target:
            target_kind = "none"

        tags = [t[:MAX_TAG_LEN] for t in split_list(tool_parameters.get("tags"))][:MAX_TAGS]

        source_module = str(tool_parameters.get("source_module") or "").strip()
        if len(source_module) > MAX_SOURCE_MODULE_LEN:
            yield self.create_text_message(
                f"来源模块（source_module）最长 {MAX_SOURCE_MODULE_LEN} 个字符，当前 {len(source_module)} 个。"
            )
            return
        link = str(tool_parameters.get("link") or "").strip()
        if len(link) > MAX_LINK_LEN:
            yield self.create_text_message(
                f"跳转链接（link）最长 {MAX_LINK_LEN} 个字符，当前 {len(link)} 个。"
            )
            return
        dedupe_key = str(tool_parameters.get("dedupe_key") or "").strip()
        if len(dedupe_key) > MAX_DEDUPE_KEY_LEN:
            yield self.create_text_message(
                f"去重键（dedupe_key）最长 {MAX_DEDUPE_KEY_LEN} 个字符，当前 {len(dedupe_key)} 个。"
            )
            return

        body: dict[str, Any] = {
            "type": msg_type,
            "title": title[:MAX_TITLE_LEN],
            "level": level,
            "target_kind": target_kind,
            "tags": tags,
            "to": {"users": to_users, "groups": to_groups, "all": to_all},
        }
        text_body = str(tool_parameters.get("body") or "").strip()
        for name, value in (("body", text_body), ("link", link), ("target", target),
                            ("source_module", source_module), ("dedupe_key", dedupe_key)):
            if value:
                body[name] = value

        try:
            resp = pisces_request("POST", "/notifications", self.runtime.credentials, json=body)
        except PiscesError as e:
            yield self.create_text_message(f"请求失败: {e}")
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
            f"（类型: {TYPE_LABELS[msg_type]}，级别: {LEVEL_LABELS[level]}）。"
        )
        yield self.create_json_message(
            {
                "notification_id": data.get("notification_id"),
                "audience": data.get("audience"),
                "type": msg_type,
                "title": title,
                "level": level,
                "source_module": source_module or None,
                "target": target or None,
                "target_kind": target_kind,
                "tags": tags,
                "to_users": to_users,
                "to_groups": to_groups,
                "to_all": to_all,
                "sent": True,
            }
        )
