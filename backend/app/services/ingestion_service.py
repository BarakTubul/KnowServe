# app/services/ingestion_service.py
import requests
import tempfile
from langchain_community.document_loaders import PyMuPDFLoader, UnstructuredFileLoader
from langchain_text_splitters import RecursiveCharacterTextSplitter
from langchain_huggingface import HuggingFaceEmbeddings
from langchain_community.vectorstores import Chroma
from app.core.chroma_client import chroma_client

class DocumentIngestionService:
    """Handles only technical ingestion: download, parse, embed, store."""

    @staticmethod
    def _convert_drive_link(url: str) -> str:
        """Convert Google Drive view link to direct download."""
        if "drive.google.com" in url and "/file/d/" in url:
            try:
                file_id = url.split("/d/")[1].split("/")[0]
                converted = f"https://drive.google.com/uc?export=download&id={file_id}"
                print(f"🔗 [Drive] Converted to direct download: {converted}")
                return converted
            except Exception as e:
                print(f"⚠️ [Drive] Failed to parse link: {e}")
        return url

    @staticmethod
    def _download_file(url: str, suffix: str = ".pdf") -> str:
        """Download file locally and return its path."""
        tmp_path = tempfile.NamedTemporaryFile(delete=False, suffix=suffix).name
        response = requests.get(url, allow_redirects=True)
        if response.status_code != 200 or not response.content:
            raise Exception(f"Download failed ({response.status_code}) for {url}")
        with open(tmp_path, "wb") as f:
            f.write(response.content)
        print(f"📥 [Downloader] File saved to {tmp_path}")
        return tmp_path

    @staticmethod
    def ingest_from_url_sync(doc_id: int, source_url: str):
        """Run the ingestion synchronously (for Celery worker)."""
        print(f"🚀 [Ingestion] Starting pipeline for doc {doc_id}")

        download_url = DocumentIngestionService._convert_drive_link(source_url)
        file_path = DocumentIngestionService._download_file(download_url)

        # Load PDF or fallback
        try:
            loader = PyMuPDFLoader(file_path)
            docs = loader.load()
        except Exception:
            loader = UnstructuredFileLoader(file_path)
            docs = loader.load()
        print(f"📄 Loaded {len(docs)} pages")

        splitter = RecursiveCharacterTextSplitter(chunk_size=1000, chunk_overlap=100)
        chunks = splitter.split_documents(docs)
        print(f"✂️ Split into {len(chunks)} chunks")

        embeddings = HuggingFaceEmbeddings(
            model_name="all-MiniLM-L6-v2",
            model_kwargs={"device": "cpu"}
        )
        vector_store = Chroma(
            client=chroma_client,
            collection_name="documents",
            embedding_function=embeddings,
        )
        vector_store.add_documents(chunks)
        print(f"💾 Stored {len(chunks)} chunks for doc {doc_id}")
        return {"doc_id": doc_id, "status": "ingested"}
