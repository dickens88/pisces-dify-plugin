"""Pisces records exposed to Dify knowledge bases, rendered as Markdown.

Pages carry a hash of this text, so a sync tool can tell which documents are stale without reading Pisces.
"""

import hashlib
import json
import threading
import time

from provider.pisces_client import PiscesError, error_message, pisces_request

SOURCE_MEMORY = "deeptrace_memory"
SOURCE_ATTACK = "attack"
SOURCE_NAMES = {SOURCE_MEMORY: "DeepTrace 公共记忆", SOURCE_ATTACK: "ATT&CK 录入"}
PAGE_TYPE = "page"

# A sync lists pages, then its blocking pipeline batch fetches one page per document while embedding;
# reuse the source listing across all of those calls (well under the 5-minute sync schedule).
_CACHE_TTL = 120
_cache: dict[str, tuple[float, dict]] = {}
_cache_lock = threading.Lock()

_KIND_NAMES = {"scenario": "攻击场景", "instance": "攻击过程", "campaign": "攻击事件", "tactic": "战术",
               "technique": "技术", "subtechnique": "子技术", "group": "攻击组织", "software": "软件",
               "mitigation": "缓解措施", "data-source": "数据源", "data-component": "数据组件",
               "detection-strategy": "检测策略", "analytic": "检测分析"}


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
        text = "\n".join([f"# 团队记忆：{n['key']}", *_lines(("类型", n.get("type")), ("摘要", n.get("description"))),
                          "", body or ""])
        records[n["mem_id"]] = {"title": n["key"], "content": text}
    return records


# ---------- ATT&CK local entries ----------

def _label(doc: dict | None) -> str:
    if not doc:
        return ""
    stix = doc["stix"]
    return f"{doc['workspace'].get('attack_id', '')} {stix.get('x_pisces_name_zh') or stix.get('name') or ''}".strip()


def _attack_records(credentials: dict) -> dict[str, dict]:
    """Reviewed, live, locally created objects; drafts, deleted and deprecated entries stay out."""
    docs = [d for d in _pages(credentials, "/attack/objects", {"origin": "custom", "state": "reviewed"}, 1000)
            if d["workspace"]["kind"] not in ("relationship", "matrix")]
    tactics = {d["stix"].get("x_mitre_shortname"): d
               for d in _pages(credentials, "/attack/objects", {"kind": "tactic"}, 1000)}
    # Objects already loaded answer most references; only the rest are fetched one by one.
    refs: dict[str, dict | None] = {d["stix"]["id"]: d for d in [*docs, *tactics.values()]}

    def ref(stix_id: str | None) -> dict | None:
        if stix_id and stix_id not in refs:
            try:
                refs[stix_id] = _get(credentials, f"/attack/objects/{stix_id}").get("data")
            except PiscesError:
                refs[stix_id] = None
        return refs.get(stix_id)

    groups: dict[str, list[str]] = {}
    if any(d["workspace"]["kind"] == "campaign" for d in docs):
        for rel in _pages(credentials, "/attack/objects", {"kind": "relationship", "origin": "custom"}, 1000):
            if rel["stix"].get("relationship_type") == "attributed-to" and (name := _label(ref(rel["stix"].get("target_ref")))):
                groups.setdefault(rel["stix"].get("source_ref"), []).append(name)

    records = {}
    for d in docs:
        stix, kind = d["stix"], d["workspace"]["kind"]
        phases = "、".join(_label(tactics.get(p.get("phase_name"))) or p.get("phase_name", "")
                          for p in stix.get("kill_chain_phases") or [])
        if kind == "scenario":
            meta = _lines(("所属技术", _label(ref(stix.get("x_pisces_parent_ref")))), ("战术", phases),
                          ("平台", "、".join(stix.get("x_mitre_platforms") or [])))
        elif kind == "instance":
            meta = _instance_lines(stix, ref(stix.get("x_pisces_event_ref")))
        elif kind == "campaign":
            meta = _lines(("事件类型", stix.get("x_pisces_event_type")), ("攻击方", "、".join(groups.get(stix["id"], []))),
                          ("时间", _period(stix)), ("业务", stix.get("x_pisces_business_service")),
                          ("环境", stix.get("x_pisces_environment")))
        else:
            meta = _lines(("别名", "、".join(stix.get("aliases") or [])), ("战术", phases))
        title = _label(d)
        if kind == "instance" and (scene := (stix.get("x_pisces_classification") or {}).get("scenario_name")):
            title = f"{title} {scene}"
        text = "\n".join([f"# {_KIND_NAMES.get(kind, kind)} {title}", *meta, "", stix.get("description") or ""])
        records[stix["id"]] = {"title": title, "content": text}
    return records


def _period(stix: dict) -> str:
    start, end = stix.get("first_seen") or "", stix.get("last_seen") or ""
    return f"{start} ~ {end}" if start or end else ""


def _instance_lines(stix: dict, event: dict | None) -> list[str]:
    c = stix.get("x_pisces_classification") or {}
    tactic = f"{c.get('tactic_name', '')}({c['tactic_id']})" if c.get("tactic_id") else ""
    mapping = " > ".join(x for x in (tactic, f"{c.get('technique_id', '')} {c.get('technique_name', '')}".strip(),
                                     f"{c.get('scenario_id', '')} {c.get('scenario_name', '')}".strip()) if x)
    det = stix.get("x_pisces_detection") or {}
    assets = "；".join(" ".join(x for x in (a.get("type"), a.get("name"), a.get("identifier"), a.get("ip")) if x)
                      for a in stix.get("x_pisces_assets") or [])
    return _lines(("所属事件", _label(event)), ("ATT&CK 映射", mapping), ("时间", _period(stix)),
                  ("攻击者", stix.get("x_pisces_actor")), ("业务", stix.get("x_pisces_business_service")),
                  ("环境", stix.get("x_pisces_environment")), ("是否执行", stix.get("x_pisces_execution")),
                  ("攻击效果", stix.get("x_pisces_effect")), ("检测结果", det.get("result")),
                  ("检测缺口", " ".join(x for x in (det.get("gap_category"), det.get("gap_reason")) if x)),
                  ("检测模型", det.get("model_refs")), ("涉及资产", assets), ("结果摘要", stix.get("x_pisces_result_summary")),
                  ("标签", "、".join(stix.get("x_pisces_tags") or [])))
