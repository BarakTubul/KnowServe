import pytest

from app.agent.tools import search_documents


@pytest.mark.asyncio
async def test_search_documents_finds_doc_20_content():
    """
    Integration test:
    - real DocsService (permissions)
    - real vector store
    - real ingested document (doc_id = 20)
    """

    # -----------------------------
    # Arrange
    # -----------------------------

    user = {
    "user_id": 12,
    "role": "EMPLOYEE",
    "departments": [5],
    }

    query = "What is the average latency of the prototype?"

    # -----------------------------
    # Act
    # -----------------------------

    results = await search_documents.ainvoke({"query":query, "user": user})
    

    # -----------------------------
    # Assert
    # -----------------------------

    assert isinstance(results, list)
    assert len(results) > 0

    # We expect doc 20 to appear
    doc_ids = {r["doc_id"] for r in results}
    assert 20 in doc_ids

    # And we expect the content to mention the latency
    joined_content = " ".join(r["content"] for r in results)

    assert "187" in joined_content or "latency" in joined_content.lower()
