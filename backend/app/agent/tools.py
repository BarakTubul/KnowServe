# tools.py

from langchain_core.tools import tool
from app.services.docs_service import DocsService


# ======================================================
# 1. SEARCH DOCUMENTS TOOL  (calls DocsService)
# ======================================================

@tool
async def search_documents(query: str, user: dict):
    """
    Search documents using existing backend logic.
    DocsService enforces permissions automatically.
    """

    department_ids = user.get("departments", [])
    
    # ⭐ Use your existing data-access logic
    # DocsService already knows which docs each department can access
    docs = []
    for dep_id in department_ids:
        allowed_docs = await DocsService.list_documents_with_access(dep_id)
        docs.extend(allowed_docs)

    # TODO: Replace this with vector search to filter docs by relevance
    # Returning all accessible docs for now:
    return docs



# ======================================================
# 2. FETCH DOCUMENT TOOL
# ======================================================

@tool
async def fetch_document(doc_id: int, user: dict):
    """
    Fetch full document using DocsService.
    Permission check is handled inside DocsService.
    """

    department_ids = user.get("departments", [])

    # Get all documents user has access to
    allowed_docs = []
    for dep_id in department_ids:
        docs = await DocsService.list_documents_with_access(dep_id)
        allowed_docs.extend(docs)

    # Check if the requested doc is allowed
    if not any(doc["id"] == doc_id for doc in allowed_docs):
        return {"error": "User does not have permission to access this document."}

    # ⭐ Fetch full doc via DB (you have a repo in DocsService)
    # You may create a new method: DocsService.get_document_full(doc_id)
    # Stub example:

    full_doc = {
        "id": doc_id,
        "title": "PLACEHOLDER",
        "content": "Full content fetched from DB"
    }

    return full_doc



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
