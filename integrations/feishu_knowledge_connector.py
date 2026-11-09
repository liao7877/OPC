"""Read-only Feishu Wiki/DOCX connectors for OPC external knowledge shadows."""
from __future__ import annotations

import hashlib
import json

from opc_integrations import Capabilities, Connector, PermanentConnectorError
from integrations.feishu_connector import FeishuBitableConnector


class FeishuDocumentConnector(Connector):
    capabilities = Capabilities(
        pull=True, push=False, delete=False, idempotency=False,
        optimistic_versioning=False, ordered_versions=True,
    )

    def __init__(self, client, resource_kind="wiki"):
        if resource_kind not in ("wiki", "docx"):
            raise ValueError("resource_kind must be wiki or docx")
        self.client = client
        self.resource_kind = resource_kind

    def pull(self, external_id):
        try:
            if self.resource_kind == "wiki":
                node = self.client.get_wiki_node(external_id)
                document = self.client.get_document(node.obj_token) if node.obj_type == "docx" else None
                fields = {
                    "title": node.title or (document.title if document else ""),
                    "node_token": node.node_token,
                    "document_id": node.obj_token,
                    "object_type": node.obj_type,
                    "revision": document.revision_id if document else None,
                }
                version = str(document.revision_id) if document and document.revision_id is not None else self._hash(fields)
            else:
                document = self.client.get_document(external_id)
                page = self.client.list_document_blocks(external_id, page_size=100)
                fields = {
                    "title": document.title,
                    "document_id": document.document_id,
                    "revision": document.revision_id,
                    "block_count": len(page.items),
                    "has_more": page.has_more,
                }
                version = str(document.revision_id) if document.revision_id is not None else self._hash(fields)
            return {"external_id": external_id, "fields": fields, "version": version, "deleted": False}
        except Exception as exc:
            raise FeishuBitableConnector._translate(self, exc) from exc

    @staticmethod
    def _hash(fields):
        raw = json.dumps(fields, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
        return hashlib.sha256(raw.encode("utf-8")).hexdigest()

    def push(self, external_id, fields, expected_version, idempotency_key):
        del external_id, fields, expected_version, idempotency_key
        raise PermanentConnectorError("Feishu knowledge write is disabled by OPC policy")

    def delete(self, external_id, expected_version, idempotency_key):
        del external_id, expected_version, idempotency_key
        raise PermanentConnectorError("Feishu knowledge delete is disabled by OPC policy")
