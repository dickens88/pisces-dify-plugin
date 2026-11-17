from collections.abc import Generator
from typing import Any

from dify_plugin.entities.datasource import (
    DatasourceGetPagesResponse,
    DatasourceMessage,
    GetOnlineDocumentPageContentRequest,
    OnlineDocumentInfo,
    OnlineDocumentPage,
)
from dify_plugin.interfaces.datasource.online_document import OnlineDocumentDatasource

from provider.knowledge import PAGE_TYPE, SOURCE_NAMES, content_hash, load_records


class PiscesKnowledgeDatasource(OnlineDocumentDatasource):
    def _get_pages(self, datasource_parameters: dict[str, Any]) -> DatasourceGetPagesResponse:
        result = []
        for source, name in SOURCE_NAMES.items():
            records = load_records(self.runtime.credentials, source)
            # The content hash stands in for an edit time: the sync tool re-indexes a page when it changes.
            pages = [OnlineDocumentPage(page_id=rid, page_name=r["title"], type=PAGE_TYPE,
                                        last_edited_time=content_hash(r["content"])) for rid, r in records.items()]
            result.append(OnlineDocumentInfo(workspace_id=source, workspace_name=name, workspace_icon="",
                                             total=len(pages), pages=pages))
        return DatasourceGetPagesResponse(result=result)

    def _get_content(self, page: GetOnlineDocumentPageContentRequest) -> Generator[DatasourceMessage, None, None]:
        record = load_records(self.runtime.credentials, page.workspace_id).get(page.page_id)
        if not record:
            raise ValueError(f"Pisces record {page.page_id} is not published in {page.workspace_id}")
        yield self.create_variable_message("content", record["content"])
        yield self.create_variable_message("page_id", page.page_id)
        yield self.create_variable_message("workspace_id", page.workspace_id)
