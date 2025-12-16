# tools.py

from langchain_core.tools import tool
from app.services.docs_service import DocsService
from app.services.document_retrieval_service import DocumentRetrievalService


# ======================================================
# 1. SEARCH DOCUMENTS TOOL  (calls DocsService)
# ======================================================

@tool
async def search_documents(query: str, user: dict):
    """
    Search documents using existing backend logic.
    Permissions enforced automatically.
    """
    return await DocumentRetrievalService.search(query, user)




# ======================================================
# 2. FETCH DOCUMENT TOOL
# ======================================================

@tool
async def fetch_document(doc_id: int, user: dict):
    """
    Fetch the full document (metadata + text content).
    Permission checks and DB lookup are handled inside DocsService.
    """

    try:
        full_doc = await DocsService.get_document_text(doc_id, user)
        return full_doc

    except ValueError as e:
        # Convert service errors into tool-friendly errors
        return {"error": str(e)}




# ======================================================
# 3. SUMMARIZE DOCUMENT TOOL
# ======================================================

@tool
def summarize_document(content: str):
    """Summarizes any text. No permission logic needed here."""
    summary = content[:200] + "..." if len(content) > 200 else content
    return {"summary": summary}



# ======================================================
# 4. LIST USER DEPARTMENTS TOOL
# ======================================================

@tool
def list_user_departments(user: dict):
    """Internal helper for LLM reasoning."""
    return {"departments": user.get("departments", [])}
