import requests
import tempfile
from langchain_community.document_loaders import PyMuPDFLoader, UnstructuredFileLoader
from langchain_text_splitters import RecursiveCharacterTextSplitter
from langchain_huggingface import HuggingFaceEmbeddings
from langchain_community.vectorstores import Chroma
from app.core.chroma_client import chroma_client
from app.core import redis_client,websocket_manager
import asyncio 

class DocumentIngestionService:
    """Uses LangChain to handle the full document ingestion pipeline (free version)."""

    # -------------------------------------------------------------
    # 🔹 Convert Google Drive 'view' link to direct download
    # -------------------------------------------------------------
    @staticmethod
    def _convert_drive_link(url: str) -> str:
        """
        Convert a Google Drive 'view' link to a direct download link.
        Example:
            https://drive.google.com/file/d/FILE_ID/view?usp=sharing
            → https://drive.google.com/uc?export=download&id=FILE_ID
        """
        if "drive.google.com" in url and "/file/d/" in url:
            try:
                file_id = url.split("/d/")[1].split("/")[0]
                converted = f"https://drive.google.com/uc?export=download&id={file_id}"
                print(f"🔗 [Drive] Converted view link to download link: {converted}")
                return converted
            except Exception as e:
                print(f"⚠️ [Drive] Failed to parse link: {e}")
        return url

    # -------------------------------------------------------------
    # 🔹 Download file (follows redirects)
    # -------------------------------------------------------------
    @staticmethod
    def _download_file(url: str, suffix: str = ".pdf") -> str:
        """
        Download a file from a URL (handles redirects) and save locally.
        Returns the file path.
        """
        tmp_path = tempfile.NamedTemporaryFile(delete=False, suffix=suffix).name
        try:
            response = requests.get(url, allow_redirects=True)
            if response.status_code == 200 and response.content:
                with open(tmp_path, "wb") as f:
                    f.write(response.content)
                print(f"📥 [Downloader] File saved to {tmp_path} ({len(response.content)} bytes)")
                return tmp_path
            else:
                raise Exception(f"Download failed ({response.status_code}) for {url}")
        except Exception as e:
            raise Exception(f"❌ [Downloader] Error downloading file: {e}")

    # -------------------------------------------------------------
    # 🔹 Main ingestion entrypoint
    # -------------------------------------------------------------
    @staticmethod
    async def ingest_from_url(doc_id: int, source_url: str, department_ids: list[int]):
        print(f"🚀 [Ingestion] Starting LangChain pipeline for doc {doc_id}")

        try:
            # 1️⃣ Convert Google Drive link if necessary
            download_url = DocumentIngestionService._convert_drive_link(source_url)

            # 2️⃣ Download and load the document
            file_path = DocumentIngestionService._download_file(download_url)

            # Try PDF loader first, fallback to unstructured loader
            try:
                loader = PyMuPDFLoader(file_path)
                docs = loader.load()
                print(f"📄 Loaded {len(docs)} page(s) from PDF file")
            except Exception as e:
                print(f"⚠️ [PDF Loader] Failed, falling back to Unstructured loader: {e}")
                loader = UnstructuredFileLoader(file_path)
                docs = loader.load()
                print(f"📄 Loaded {len(docs)} document(s) via fallback loader")

            # 3️⃣ Chunk the document into segments
            splitter = RecursiveCharacterTextSplitter(chunk_size=1000, chunk_overlap=100)
            chunks = splitter.split_documents(docs)
            print(f"✂️ [Chunker] Split into {len(chunks)} chunks")

            # 4️⃣ Embed the chunks (🆓 Local embeddings with Hugging Face)
            try:
                embeddings = HuggingFaceEmbeddings(
                    model_name="all-MiniLM-L6-v2",
                    model_kwargs={"device": "cpu"}  # or "cuda" for GPU
                )
                print("🧠 [Embedder] Using local HuggingFace embeddings (all-MiniLM-L6-v2)")
            except Exception as e:
                raise Exception(f"Failed to initialize local embeddings: {e}")

            # 5️⃣ Store in Chroma
            try:
                vector_store = Chroma(
                    client=chroma_client,
                    collection_name="documents",
                    embedding_function=embeddings,
                )
                vector_store.add_documents(chunks)
                print(f"💾 [Chroma] Stored {len(chunks)} chunks for doc {doc_id}")
            except Exception as e:
                raise Exception(f"Failed to store embeddings in Chroma: {e}")

            # 6️⃣ Update DB status → ingested
            DocumentIngestionService._update_status(doc_id, "ingested")
            print(f"✅ [Ingestion] Completed successfully for doc {doc_id}")

            if redis_client:
                redis_client.delete("docs:all")
                for dep_id in department_ids:
                    redis_client.delete(f"docs:department:{dep_id}")
                print(f"🧹 [Ingestion] Cache invalidated after doc {doc_id} ingestion")

            asyncio.run(websocket_manager.manager.send_status(doc_id, "ingested", "Ingestion completed successfully"))
        except Exception as e:
            # Centralized error handling: update DB + re-raise
            print(f"❌ [Ingestion] Fatal error for doc {doc_id}: {e}")
            DocumentIngestionService._update_status(doc_id, "failed")
            raise  # ✅ Propagate to run_background()

    # -------------------------------------------------------------
    # 🔹 Helper to update DB status
    # -------------------------------------------------------------
    @staticmethod
    def _update_status(doc_id: int, status: str):
        """Update the document status in the PostgreSQL database."""
        from app.core.database import SessionLocal
        from app.models.document import Document

        db = SessionLocal()
        try:
            doc = db.query(Document).filter(Document.id == doc_id).first()
            if doc:
                doc.status = status
                db.commit()
                print(f"📘 [DB] Document {doc_id} status updated → '{status}'")
        except Exception as e:
            print(f"❌ [DB] Failed to update document status: {e}")
        finally:
            db.close()
