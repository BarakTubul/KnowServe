from unittest.mock import patch, MagicMock
from app.services.ingestion_service import DocumentIngestionService


def test_extract_text_from_url_basic_pdf():
    """Ensure extract_text_from_url loads a PDF, concatenates pages."""

    fake_path = "/tmp/file.pdf"

    # Fake docs returned by loader
    fake_docs = [
        MagicMock(page_content="Page 1 text"),
        MagicMock(page_content="Page 2 text"),
    ]

    with patch.object(DocumentIngestionService, "_convert_drive_link", return_value="http://fake.pdf"):
        with patch.object(DocumentIngestionService, "_download_file", return_value=fake_path):

            # Mock PyMuPDFLoader.load()
            fake_loader = MagicMock()
            fake_loader.load.return_value = fake_docs

            with patch("app.services.ingestion_service.PyMuPDFLoader", return_value=fake_loader):

                full_text = DocumentIngestionService.extract_text_from_url("http://fake.pdf")

                assert "Page 1 text" in full_text
                assert "Page 2 text" in full_text
                assert full_text == "Page 1 text\nPage 2 text"


def test_extract_text_from_url_fallback_unstructured():
    """If PyMuPDFLoader fails → fallback to UnstructuredFileLoader."""

    fake_path = "/tmp/file.pdf"
    fake_docs = [MagicMock(page_content="fallback text")]

    with patch.object(DocumentIngestionService, "_convert_drive_link", return_value="http://fake.pdf"):
        with patch.object(DocumentIngestionService, "_download_file", return_value=fake_path):

            # Make PyMuPDFLoader throw error
            with patch("app.services.ingestion_service.PyMuPDFLoader", side_effect=Exception("PDF error")):

                # Mock fallback loader
                fake_loader = MagicMock()
                fake_loader.load.return_value = fake_docs

                with patch("app.services.ingestion_service.UnstructuredFileLoader", return_value=fake_loader):

                    text = DocumentIngestionService.extract_text_from_url("http://fake.pdf")

                    assert text == "fallback text"
