import requests
import tempfile
import gdown
import os
from langchain_community.document_loaders import PyMuPDFLoader
from langchain_text_splitters import RecursiveCharacterTextSplitter
from app.core.vector_store import get_vector_store


class DocumentIngestionService:
    """
    Handles ONLY technical ingestion:
    - download
    - validate
    - parse
    - chunk
    - embed
    - store
    """

    @staticmethod
    def _extract_drive_file_id(url: str) -> str | None:
        """
        Extract file ID from Google Drive share URL.
        Supports:
        - https://drive.google.com/file/d/<ID>/view
        """
        if "drive.google.com" not in url:
            return None

        if "/file/d/" in url:
            return url.split("/file/d/")[1].split("/")[0]

        return None


    # ---------------------------------------------------------
    # 🔹 Google Drive handling
    # ---------------------------------------------------------
    @staticmethod
    def _download_file(url: str, suffix: str = ".pdf") -> str:
        """
        Download a file locally.
        - Google Drive → gdown
        - Other URLs → requests
        """
        tmp_path = tempfile.NamedTemporaryFile(delete=False, suffix=suffix).name

        # 1️⃣ Google Drive → gdown
        file_id = DocumentIngestionService._extract_drive_file_id(url)
        if file_id:
            print(f"📥 [Downloader] Using gdown for Drive file {file_id}")
            drive_url = f"https://drive.google.com/uc?id={file_id}"
            gdown.download(drive_url, tmp_path, quiet=False)

            if not os.path.exists(tmp_path) or os.path.getsize(tmp_path) == 0:
                raise RuntimeError("gdown failed to download file")

            return tmp_path

        else:
            raise ValueError("Invalid Drive Link!")


    # ---------------------------------------------------------
    # 🔹 Validation
    # ---------------------------------------------------------
    @staticmethod
    def _assert_pdf(file_path: str):
        """
        Ensure the downloaded file is actually a PDF.
        Prevents indexing HTML / Drive UI garbage.
        """
        import magic

        mime = magic.from_file(file_path, mime=True)
        if mime != "application/pdf":
            raise ValueError(
                f"Ingestion failed: expected application/pdf, got {mime}"
            )

    # ---------------------------------------------------------
    # 🔹 Text extraction (used elsewhere)
    # ---------------------------------------------------------
    @staticmethod
    def extract_text_from_url(url: str) -> str:
        """
        Extract raw text from a valid PDF URL.
        """
        file_path = DocumentIngestionService._download_file(url)

        DocumentIngestionService._assert_pdf(file_path)

        loader = PyMuPDFLoader(file_path)
        docs = loader.load()

        if not docs or not any(d.page_content.strip() for d in docs):
            raise ValueError("PDF contains no extractable text")

        return "\n".join(d.page_content for d in docs)

    # ---------------------------------------------------------
    # 🔹 Main ingestion pipeline (Celery-safe)
    # ---------------------------------------------------------
    @staticmethod
    def ingest_from_url_sync(doc_id: int, source_url: str):
        """
        Run ingestion synchronously (Celery worker).
        This method FAILS FAST on invalid input.
        """
        print(f"🚀 [Ingestion] Starting pipeline for doc {doc_id}")

        # 1️⃣ Download
        file_path = DocumentIngestionService._download_file(source_url)

        # 2️⃣ Validate
        #DocumentIngestionService._assert_pdf(file_path)

        # 3️⃣ Load PDF (STRICT — no HTML fallback)
        loader = PyMuPDFLoader(file_path)
        docs = loader.load()

        if not docs or not any(d.page_content.strip() for d in docs):
            raise ValueError("Ingestion failed: empty or non-text PDF")

        print(f"📄 Loaded {len(docs)} pages")

        # 4️⃣ Chunk
        splitter = RecursiveCharacterTextSplitter(
            chunk_size=1000,
            chunk_overlap=100,
        )
        chunks = splitter.split_documents(docs)

        if not chunks:
            raise ValueError("Ingestion failed: no chunks produced")

        # 5️⃣ Attach metadata (CRITICAL)
        for c in chunks:
            c.metadata["doc_id"] = doc_id

        print(f"✂️ Split into {len(chunks)} chunks")

        # 6️⃣ Store in vector DB
        vector_store = get_vector_store()
        vector_store.add_documents(chunks)

        print(f"💾 Stored {len(chunks)} chunks for doc {doc_id}")

        return {
            "doc_id": doc_id,
            "status": "ingested",
            "chunks": len(chunks),
        }
