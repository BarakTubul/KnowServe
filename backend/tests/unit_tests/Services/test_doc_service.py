import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from app.services.docs_service import DocsService



@pytest.mark.asyncio
async def test_get_document_text_access_denied():
    """User has no department access → should raise Value Error."""

    user = {"departments": [1]}

    # Mock DocsService.list_documents_with_access to return NO docs
    with patch.object(DocsService, "list_documents_with_access", new=AsyncMock(return_value=[])):
        with pytest.raises(ValueError):
            await DocsService.get_document_text(doc_id=99, user=user)


@pytest.mark.asyncio
async def test_get_document_text_not_found():
    """User has access, but DB does not contain the document → NotFoundError."""

    user = {"departments": [1]}

    # Mock to SAY user *does* have access to doc 5
    with patch.object(DocsService, "list_documents_with_access", new=AsyncMock(return_value=[{"id": 5}])):

        # Mock LlamaIndex Retrieval to return []
        with patch("app.services.docs_service.get_llama_index") as mock_get_index:
            
            mock_retriever = AsyncMock()
            mock_retriever.aretrieve.return_value = []
            
            mock_index = MagicMock()
            mock_index.as_retriever.return_value = mock_retriever
            mock_get_index.return_value = mock_index

            with pytest.raises(ValueError, match="No Access or document is empty!"):
                await DocsService.get_document_text(doc_id=5, user=user)


@pytest.mark.asyncio
async def test_get_document_text_success():
    """Full happy path — access granted + doc exists + ingestion returns text."""

    user = {"departments": [1]}

    # 1) User has access
    with patch.object(DocsService, "list_documents_with_access", new=AsyncMock(return_value=[{"id": 7}])):

        # 2) Fake DB document object
        fake_doc = MagicMock()
        fake_doc.id = 7
        fake_doc.title = "Employee Handbook"
        fake_doc.source_url = "https://example.com/doc7.pdf"

        # 3) Mock UnitOfWork to return fake document
        with patch("app.services.docs_service.UnitOfWork") as MockUOW:
            mock_uow_instance = MockUOW.return_value.__enter__.return_value
            mock_uow_instance.documents.get.return_value = fake_doc

            # 4) Mock LlamaIndex Retrieval
            with patch("app.services.docs_service.get_llama_index") as mock_get_index:
                
                # Setup Retriever mock
                mock_node = MagicMock()
                mock_node.get_content.return_value = "FULL PDF TEXT"
                
                mock_retriever = AsyncMock()
                mock_retriever.aretrieve.return_value = [mock_node]
                
                mock_index = MagicMock()
                mock_index.as_retriever.return_value = mock_retriever
                
                mock_get_index.return_value = mock_index
                
                result = await DocsService.get_document_text(doc_id=7, user=user)

                assert result["id"] == 7
                assert result["content"] == "FULL PDF TEXT"
