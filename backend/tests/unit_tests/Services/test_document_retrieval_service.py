import pytest
from types import SimpleNamespace

from app.services.document_retrieval_service import DocumentRetrievalService


@pytest.mark.asyncio
async def test_search_filters_by_permissions(monkeypatch):
    """
    Ensure retrieval:
    - fetches allowed documents per department
    - filters vector results by allowed doc_ids
    - returns at most k chunks
    """

    # -----------------------------
    # Arrange
    # -----------------------------

    user = {
        "id": 123,
        "departments": [1],
    }

    # Mock DocsService.list_documents_with_access
    async def mock_list_documents_with_access(department_id: int):
        assert department_id == 1
        return [
            {"id": 1, "title": "Doc 1"},
            {"id": 2, "title": "Doc 2"},
        ]

    monkeypatch.setattr(
        "app.services.document_retrieval_service.DocsService.list_documents_with_access",
        mock_list_documents_with_access,
    )

    # Fake vector search results
    fake_results = [
        SimpleNamespace(
            page_content="Content from doc 1",
            metadata={"doc_id": 1},
            score=0.9,
        ),
        SimpleNamespace(
            page_content="Content from doc 3 (unauthorized)",
            metadata={"doc_id": 3},
            score=0.85,
        ),
        SimpleNamespace(
            page_content="Content from doc 2",
            metadata={"doc_id": 2},
            score=0.8,
        ),
    ]

    class FakeVectorStore:
        def similarity_search(self, query, k):
            # Verify over-fetching behavior
            assert k == 6 * 3
            assert query == "test query"
            return fake_results

    def mock_get_vector_store():
        return FakeVectorStore()

    monkeypatch.setattr(
        "app.services.document_retrieval_service.get_vector_store",
        mock_get_vector_store,
    )

    # -----------------------------
    # Act
    # -----------------------------

    results = await DocumentRetrievalService.search(
        query="test query",
        user=user,
        k=6,
    )

    # -----------------------------
    # Assert
    # -----------------------------

    assert len(results) == 2

    doc_ids = {r["doc_id"] for r in results}
    assert doc_ids == {1, 2}

    for r in results:
        assert "content" in r
        assert "doc_id" in r
        assert "score" in r
