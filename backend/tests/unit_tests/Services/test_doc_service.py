import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from app.services.docs_service import DocsService
from app.services.ingestion_service import DocumentIngestionService



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

        # Mock UnitOfWork + repo to return None → doc missing
        with patch("app.services.docs_service.UnitOfWork") as MockUOW:
            mock_uow_instance = MockUOW.return_value.__enter__.return_value
            mock_uow_instance.documents.get.return_value = None

            with pytest.raises(ValueError):
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

            # 4) Mock text extraction
            with patch.object(DocumentIngestionService, "extract_text_from_url", return_value="FULL PDF TEXT"):
                
                result = await DocsService.get_document_text(doc_id=7, user=user)

                assert result["id"] == 7
                assert result["title"] == "Employee Handbook"
                assert result["content"] == "FULL PDF TEXT"
