import os
import tempfile
from unittest.mock import patch, MagicMock
from app.services.ingestion_service import DocumentIngestionService


def test_extract_drive_file_id_valid():
    """Ensure it extracts the correct ID from a standard Google Drive URL."""
    url = "https://drive.google.com/file/d/1rkIxRxT-pV8lqfwUQoTjbspFxWTsRk6E/view?usp=sharing"
    file_id = DocumentIngestionService._extract_drive_file_id(url)
    assert file_id == "1rkIxRxT-pV8lqfwUQoTjbspFxWTsRk6E"

def test_extract_drive_file_id_invalid():
    """Ensure it returns None for non-Drive URLs."""
    url = "https://example.com/file.pdf"
    assert DocumentIngestionService._extract_drive_file_id(url) is None

def test_extract_documents_from_url():
    """Mock the download and PyMuPDFReader to verify LlamaIndex document metadata attachment."""
    fake_path = os.path.join(tempfile.gettempdir(), "test_file.pdf")
    
    # Fake LlamaIndex docs returned by reader
    fake_doc1 = MagicMock()
    fake_doc1.metadata = {}
    
    # Mock download and the LlamaIndex PyMuPDFReader
    with patch.object(DocumentIngestionService, "_download_file", return_value=fake_path):
        with patch("llama_index.readers.file.PyMuPDFReader") as MockReader:
            
            mock_reader_instance = MockReader.return_value
            mock_reader_instance.load.return_value = [fake_doc1]
            
            # Setup metadata param
            metadata = {"db_doc_id": 99}
            
            docs = DocumentIngestionService.extract_documents_from_url("http://fake.pdf", metadata)
            
            assert len(docs) == 1
            # Verify the method attached the passed metadata into the document
            assert docs[0].metadata["db_doc_id"] == 99
