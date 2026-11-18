"""Pisces records exposed to Dify knowledge bases, rendered as Markdown.

Pages carry a hash of this text, so a sync tool can tell which documents are stale without reading Pisces.
"""

import hashlib
import json
import re
import threading
import time

from provider.pisces_client import PiscesError, error_message, pisces_request

SOURCE_MEMORY = "deeptrace_memory"
SOURCE_ATTACK = "attack"
SOURCE_NAMES = {SOURCE_MEMORY: "DeepTrace 公共记忆", SOURCE_ATTACK: "ATT&CK 攻击事件"}
PAGE_TYPE = "page"

# Labels as the Pisces UI shows them (web/src/i18n/locales/zh-CN.json, attack.*).
_EVENT_TYPES = {"red_blue_exercise": "红蓝对抗", "validation": "协防测试", "external_attack": "外部攻击"}
_DETECTIONS = {"detected": "已监控到", "not_detected": "未监控到", "unknown": "待核查"}
_GAPS = {"logs_missing": "日志未采集", "fields_missing": "日志字段缺失", "rule_missing": "规则未覆盖",
         "rule_disabled": "规则未启用或运行异常", "alert_handling": "告警未有效处置", "other": "其他原因"}
_ASSETS = {"host": "主机", "account": "账号", "container": "容器", "database": "数据库", "obs_bucket": "OBS桶",
           "cloud_service": "云服务", "resource": "其他资源"}

# A sync lists pages, then its blocking pipeline batch fetches one page per document while embedding;
# reuse the source listing across all of those calls (well under the 5-minute sync schedule).
_CACHE_TTL = 120
_cache: dict[str, tuple[float, dict]] = {}
_cache_lock = threading.Lock()


def content_hash(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _get(credentials: dict, path: str, params: dict | None = None) -> dict:
    resp = pisces_request("GET", path, credentials, params=params)
    if not resp.ok:
        raise PiscesError(f"GET {path} failed ({resp.status_code}): {error_message(resp)}")
    return resp.json()


def _pages(credentials: dict, path: str, params: dict, limit: int) -> list[dict]:
    rows, page = [], 1
    while True:
        body = _get(credentials, path, {**params, "page": page, "limit": limit})
        rows += body.get("data") or []
        if not body.get("data") or len(rows) >= body.get("total", 0):
            return rows
        page += 1


def _lines(*pairs) -> list[str]:
    return [f"- {label}：{value}" for label, value in pairs if value]


def load_records(credentials: dict, source: str) -> dict[str, dict]:
    """{record_id: {title, content}} of everything the source currently publishes."""
    loader = {SOURCE_MEMORY: _memory_records, SOURCE_ATTACK: _attack_records}.get(source)
    if not loader:
        raise ValueError(f"unknown Pisces source {source!r}")
    # Hashed so no password sits in a dict key.
    key = content_hash(source + "\0" + json.dumps(credentials, sort_keys=True, default=str))
    with _cache_lock:
        hit = _cache.get(key)
        if hit and time.time() - hit[0] < _CACHE_TTL:
            return hit[1]
    records = loader(credentials)
    now = time.time()
    with _cache_lock:
        for k in [k for k, (at, _) in _cache.items() if now - at >= _CACHE_TTL]:
            del _cache[k]
        _cache[key] = (now, records)
    return records


# ---------- DeepTrace team memory ----------

def _memory_records(credentials: dict) -> dict[str, dict]:
    notes = _pages(credentials, "/deeptrace/memory/notes", {"scope": "shared", "status": "active"}, 100)
    records = {}
    for n in notes:
        value = n.get("value")
        body = value if isinstance(value, str) else json.dumps(value, ensure_ascii=False, indent=2)
        # No blank line inside: the pipeline splits chunks on blank lines, and a note is one chunk.
        text = "\n".join([f"# 团队记忆：{n['key']}", *_lines(("类型", n.get("type")), ("摘要", n.get("description"))),
                          _paragraph(body)]).strip()
        records[n["mem_id"]] = {"title": n["key"], "content": text}
    return records


# ---------- ATT&CK events ----------

def _label(doc: dict | None) -> str:
    if not doc:
        return ""
    stix = doc["stix"]
    return f"{doc['workspace'].get('attack_id', '')} {stix.get('x_pisces_name_zh') or stix.get('name') or ''}".strip()


def _attack_records(credentials: dict) -> dict[str, dict]:
    """One document per confirmed local event, holding its confirmed procedures; drafts and deleted entries stay out."""
    events = _pages(credentials, "/attack/objects", {"origin": "custom", "kind": "campaign", "state": "reviewed"}, 1000)
    if not events:
        return {}
    procedures: dict[str, list[dict]] = {}
    for d in _pages(credentials, "/attack/objects", {"origin": "custom", "kind": "instance", "state": "reviewed"}, 1000):
        procedures.setdefault(d["stix"].get("x_pisces_event_ref"), []).append(d)
    groups: dict[str, list[str]] = {}
    for rel in _pages(credentials, "/attack/objects", {"kind": "relationship", "origin": "custom"}, 1000):
        if rel["stix"].get("relationship_type") == "attributed-to":
            try:
                group = _get(credentials, f"/attack/objects/{rel['stix'].get('target_ref')}").get("data")
            except PiscesError:
                group = None
            if (name := _label(group)):
                groups.setdefault(rel["stix"].get("source_ref"), []).append(name)

    records = {}
    for event in events:
        stix, title = event["stix"], _label(event)
        steps = sorted(procedures.get(stix["id"], []),
                       key=lambda d: (d["stix"].get("first_seen") or "~", d["stix"].get("x_pisces_number") or 0))
        head = "\n".join([f"# 攻击事件 {title}",
                          *_lines(("事件类型", _EVENT_TYPES.get(stix.get("x_pisces_event_type"), stix.get("x_pisces_event_type"))), ("攻击方", "、".join(groups.get(stix["id"], []))),
                                  ("时间", _period(stix)), ("业务", stix.get("x_pisces_business_service")),
                                  ("环境", stix.get("x_pisces_environment")), ("已确认攻击过程", f"{len(steps)} 条")),
                          _paragraph(stix.get("description"))])
        blocks = [head]
        for d in steps:
            # The pipeline splits chunks on blank lines: one chunk per procedure, so each names its event.
            scene = (d["stix"].get("x_pisces_classification") or {}).get("scenario_name") or ""
            blocks.append("\n".join([f"## 攻击过程 {d['workspace'].get('attack_id', '')} {scene}（事件 {title}）".replace("  ", " "),
                                     *_instance_lines(d["stix"]), _paragraph(d["stix"].get("description"))]))
        records[stix["id"]] = {"title": title, "content": "\n\n".join(b.strip() for b in blocks)}
    return records


def _paragraph(text: str | None) -> str:
    return re.sub(r"\n\s*\n+", "\n", (text or "").strip())


def _period(stix: dict) -> str:
    start, end = stix.get("first_seen") or "", stix.get("last_seen") or ""
    return f"{start} ~ {end}" if start or end else ""


def _instance_lines(stix: dict) -> list[str]:
    """What the procedure form shows up front; the optional "补充信息" fields stay out of the knowledge base."""
    c = stix.get("x_pisces_classification") or {}
    tactic = f"{c.get('tactic_name', '')}({c['tactic_id']})" if c.get("tactic_id") else ""
    mapping = " > ".join(x for x in (tactic, f"{c.get('technique_id', '')} {c.get('technique_name', '')}".strip(),
                                     f"{c.get('scenario_id', '')} {c.get('scenario_name', '')}".strip()) if x)
    det = stix.get("x_pisces_detection") or {}
    gap = " ".join(x for x in (_GAPS.get(det.get("gap_category"), det.get("gap_category")), det.get("gap_reason")) if x)
    assets = "；".join(" ".join(x for x in (_ASSETS.get(a.get("type"), a.get("type")), a.get("name"), a.get("identifier"),
                                           a.get("ip")) if x)
                      for a in stix.get("x_pisces_assets") or [])
    return _lines(("ATT&CK 映射", mapping), ("监控结果", _DETECTIONS.get(det.get("result"), det.get("result"))),
                  ("检测缺口", gap), ("涉及资产", assets), ("标签", "、".join(stix.get("x_pisces_tags") or [])))
