"""One-way sync of a Pisces source into a Dify pipeline knowledge base, through Dify's API only.

The Pisces datasource lists pages with a content hash as last_edited_time. Each document carries pisces_id/pisces_hash
metadata, so a run is stateless: it indexes changed pages and removes a superseded document only once its
replacement has finished indexing.
"""

import json
from collections.abc import Generator
from typing import Any

import requests
from dify_plugin import Tool
from dify_plugin.entities.tool import ToolInvokeMessage

META_ID, META_HASH = "pisces_id", "pisces_hash"
DATASOURCE_PLUGIN = "charles/pisces_datasource"


class DifyKnowledge:
    def __init__(self, base_url: str, api_key: str, dataset_id: str):
        self.base = f"{base_url.rstrip('/')}/v1/datasets/{dataset_id}"
        self.http = requests.Session()
        self.http.headers["Authorization"] = f"Bearer {api_key}"

    def send(self, method: str, path: str = "", ok: tuple[int, ...] = (), **kwargs) -> requests.Response:
        """The raw response; any status >= 400 not listed in `ok` raises."""
        kwargs.setdefault("timeout", 20)
        resp = self.http.request(method, self.base + path, **kwargs)
        if resp.status_code >= 400 and resp.status_code not in ok:
            raise RuntimeError(f"Dify {method} {path or '/'} failed ({resp.status_code}): {resp.text[:300]}")
        return resp

    def call(self, method: str, path: str = "", **kwargs) -> dict:
        resp = self.send(method, path, **kwargs)
        return resp.json() if resp.content else {}

    def delete_document(self, doc_id: str) -> None:
        self.send("DELETE", f"/documents/{doc_id}", ok=(404,))  # already gone is fine

    def documents(self) -> list[dict]:
        docs, page = [], 1
        while True:
            body = self.call("GET", "/documents", params={"page": page, "limit": 100})
            docs += body.get("data") or []
            if not body.get("has_more"):
                return docs
            page += 1

    def metadata_fields(self) -> dict[str, str]:
        fields = {f["name"]: f["id"] for f in self.call("GET", "/metadata").get("doc_metadata") or []}
        for name in (META_ID, META_HASH):
            if name not in fields:
                fields[name] = self.call("POST", "/metadata", json={"type": "string", "name": name})["id"]
        return fields

    def start_node(self) -> tuple[str, str]:
        """The Pisces datasource node and its default credential; runs must name the credential explicitly."""
        for node in self.call("GET", "/pipeline/datasource-plugins"):
            if node.get("plugin_id") == DATASOURCE_PLUGIN and node.get("datasource_type") == "online_document":
                creds = node.get("credentials") or []
                cred = next((c for c in creds if c.get("is_default")), creds[0] if creds else None)
                if not cred:
                    raise RuntimeError("the Pisces datasource has no credential configured in Dify")
                return node["node_id"], cred["id"]
        raise RuntimeError("the published pipeline has no Pisces datasource node")

    def pages(self, node_id: str, credential_id: str, workspace_id: str) -> dict[str, dict]:
        """{page_id: page} the datasource currently offers in one workspace."""
        resp = self.send("POST", f"/pipeline/datasource/nodes/{node_id}/run", stream=True, timeout=25,
                         json={"inputs": {}, "datasource_type": "online_document", "is_published": True,
                               "credential_id": credential_id})
        for line in resp.iter_lines(decode_unicode=True):
            if not line or not line.startswith("data:"):
                continue
            event = json.loads(line[5:])
            if event.get("event") == "datasource_error":
                raise RuntimeError(f"Pisces datasource failed: {event.get('error')}")
            if event.get("event") == "datasource_completed":
                for ws in event.get("data") or []:
                    if ws.get("workspace_id") == workspace_id:
                        return {p["page_id"]: p for p in ws.get("pages") or []}
                raise RuntimeError(f"the Pisces datasource offers no workspace {workspace_id}")
        raise RuntimeError("the datasource run ended without a result")


class SyncKnowledgeBaseTool(Tool):
    def _invoke(self, tool_parameters: dict[str, Any]) -> Generator[ToolInvokeMessage, None, None]:
        source = tool_parameters["source"]
        kb = DifyKnowledge(tool_parameters["dify_api_base"], tool_parameters["dataset_api_key"],
                           tool_parameters["dataset_id"].strip())
        batch_size = max(1, int(tool_parameters.get("batch_size") or 5))
        node_id, credential_id = kb.start_node()
        records = kb.pages(node_id, credential_id, source)

        fields = kb.metadata_fields()
        by_record: dict[str, list[tuple[str | None, dict]]] = {}  # pisces_id -> [(pisces_hash, doc)]
        for doc in kb.documents():
            meta = {m["name"]: m.get("value") for m in doc.get("doc_metadata") or []}
            if (rid := meta.get(META_ID)):
                by_record.setdefault(rid, []).append((meta.get(META_HASH), doc))

        delete = [doc for rid, docs in by_record.items() if rid not in records for _, doc in docs]
        todo, pending = [], 0
        for rid, record in records.items():
            docs = [doc for _, doc in by_record.get(rid, [])]
            fresh = [doc for h, doc in by_record.get(rid, []) if h == record["last_edited_time"]]
            done = next((d for d in fresh if d.get("indexing_status") == "completed"), None)
            if done:  # keep one finished copy of the current content, drop everything else
                delete += [d for d in docs if d is not done]
                continue
            failed = [d for d in fresh if d.get("indexing_status") == "error"]
            delete += failed
            if len(fresh) > len(failed):  # any other status is still on its way to completed or error
                pending += 1
            else:
                todo.append(record)

        for doc in delete:
            kb.delete_document(doc["id"])

        queued = max(0, len(todo) - batch_size)
        todo = todo[:batch_size]
        if todo:
            run = kb.call("POST", "/pipeline/run", json={
                "inputs": {}, "datasource_type": "online_document", "start_node_id": node_id,
                "is_published": True, "response_mode": "blocking",
                "datasource_info_list": [{"workspace_id": source, "credential_id": credential_id,
                                          "page": {"page_id": r["page_id"], "page_name": r["page_name"],
                                                   "type": r["type"]}}
                                         for r in todo]})
            created = [doc["id"] for doc in run.get("documents") or []]
            try:
                kb.call("POST", "/documents/metadata", json={"operation_data": [
                    {"document_id": doc_id, "metadata_list": [
                        {"id": fields[META_ID], "name": META_ID, "value": r["page_id"]},
                        {"id": fields[META_HASH], "name": META_HASH, "value": r["last_edited_time"]}]}
                    for doc_id, r in zip(created, todo)]})
            except Exception:
                for doc_id in created:  # untagged documents could never be matched or cleaned up again
                    kb.delete_document(doc_id)
                raise

        s = {"source": source, "records": len(records), "started": len(todo), "indexing": pending,
             "removed": len(delete), "queued": queued}
        yield self.create_text_message(
            f"{s['source']}: {s['records']} 条记录，本次提交 {s['started']} 条、删除 {s['removed']} 篇、"
            f"{s['indexing']} 条索引中、{s['queued']} 条留待下次。")
        yield self.create_json_message(s)
