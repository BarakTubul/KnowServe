import os
import gdown
import tempfile

from app.core.vector_store import get_llama_index

class DocumentIngestionService:
    
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
    def _download_file(url: str, doc_id: int = None, suffix: str = ".pdf") -> str:
        """
        Download a file locally. If doc_id is provided, saves persistently to /static/docs.
        """
        if doc_id:
            static_dir = os.path.join(os.path.dirname(os.path.dirname(__file__)), "static", "docs")
            os.makedirs(static_dir, exist_ok=True)
            tmp_path = os.path.join(static_dir, f"{doc_id}{suffix}")
        else:
            tmp_path = tempfile.NamedTemporaryFile(delete=False, suffix=suffix).name

        # 1️⃣ Google Drive → gdown
        file_id = DocumentIngestionService._extract_drive_file_id(url)
        if file_id:
            print(f"📥 [Downloader] Using gdown for Drive file {file_id}. Saving to {tmp_path}")
            drive_url = f"https://drive.google.com/uc?id={file_id}"
            gdown.download(drive_url, tmp_path, quiet=False)

            if not os.path.exists(tmp_path) or os.path.getsize(tmp_path) == 0:
                raise RuntimeError("gdown failed to download file")

            return tmp_path

        else:
            raise ValueError("Invalid Drive Link!")
    
    @staticmethod
    def extract_documents_from_url(source_url: str, metadata: dict) -> list['Document']:
        """
        Downloads a PDF and returns a list of LlamaIndex Document objects.
        """
        doc_id = metadata.get("db_doc_id")
        
        # 1. Reuse your existing download logic (persistent if doc_id provided)
        file_path = DocumentIngestionService._download_file(source_url, doc_id=doc_id)
        
        try:
            # 2. Use LlamaIndex PyMuPDFReader
            from llama_index.readers.file import PyMuPDFReader
            reader = PyMuPDFReader()
            documents = reader.load(file_path=file_path)

            # 3. Attach common metadata to every Document object
            for doc in documents:
                doc.metadata.update(metadata)
            
            return documents
        finally:
            # Cleanup temp file only if it was a temporary ingestion
            if not doc_id and os.path.exists(file_path):
                os.remove(file_path)

    @staticmethod
    def ingest_from_url_sync(doc_id: int, source_url: str, department_ids: list[int]):
        """
        Main entry point for Celery or API calls.
        Now uses the unified extraction method.
        """
        # 1. Prepare metadata for this specific document
        metadata = {
            "db_doc_id": doc_id,
            "allowed_department_ids": department_ids
        }

        # 2. Extract using the unified method
        documents = DocumentIngestionService.extract_documents_from_url(source_url, metadata)

        # 3. Process into Nodes and Store
        index = get_llama_index()
        
        # SentenceSplitter is token-aware and better for RAG than character splitting
        from llama_index.core.node_parser import SentenceSplitter
        splitter = SentenceSplitter(chunk_size=1024, chunk_overlap=100)
        
        # This will split the documents and insert them into ChromaDB
        nodes = splitter.get_nodes_from_documents(documents)

        # 🔐 attach security metadata (only db_doc_id, no department info)
        for node in nodes:
            node.metadata.pop("allowed_department_ids", None)
            node.metadata["db_doc_id"] = int(doc_id)

        index.insert_nodes(nodes)

        return {
            "doc_id": doc_id,
            "status": "ingested",
            "nodes_count": len(nodes)
        }



    