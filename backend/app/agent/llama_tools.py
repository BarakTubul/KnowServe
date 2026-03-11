from typing import Annotated
import time

from app.services.docs_service import DocsService
from app.core.vector_store import get_llama_index
from llama_index.core.workflow import Context

from app.services.docs_service import DocsService
from app.core.vector_store import get_llama_index


# ---------------------------------------------------------
# SEARCH TOOL
# ---------------------------------------------------------
async def search_documents_tool(
    ctx: Context,
    query: Annotated[str, "The search query"]
):
    """
    Semantic search over documents with department-based authorization.
    """

    # pull departments from workflow state
    user_dept_ids = await ctx.store.get("user_dept_ids") or []

    # safety guard
    if not user_dept_ids:
        return "No departments are associated with your account."

    # 1. Fetch allowed document IDs from PostgreSQL
    allowed_doc_ids = set()
    for dept_id in user_dept_ids:
        docs = await DocsService.list_documents_with_access(dept_id)
        for d in docs:
            allowed_doc_ids.add(d["id"])
            
    if not allowed_doc_ids:
        return "You do not have access to any documents."

    index = get_llama_index()

    from llama_index.core.vector_stores import MetadataFilter, MetadataFilters, FilterOperator

    # 2. Filter Vector DB by allowed doc_ids instead of dept_id
    filters = MetadataFilters(
        filters=[
            MetadataFilter(
                key="db_doc_id",
                value=list(allowed_doc_ids),
                operator=FilterOperator.IN
            )
        ]
    )

    query_engine = index.as_query_engine(
        filters=filters,
        similarity_top_k=6
    )

    try:
        start_q = time.time()
        response = await query_engine.aquery(query)
        print(f"\n[PROFILER] Query Engine aquery() took {time.time() - start_q:.3f}s")
        print("\n================ RETRIEVAL DEBUG ================")

        if not response.source_nodes:
            print("NO NODES RETURNED")
            return "No relevant information found in your accessible documents."
            
        formatted_results = []
        for i, node in enumerate(response.source_nodes):
            print(f"\n--- NODE {i+1} ---")
            title = node.node.metadata.get('title', 'Unknown Document')
            text = node.node.text
            print("Score:", node.score)
            print("Metadata:", node.node.metadata)
            print("Text Preview:", text[:300])
            
            formatted_results.append(f"Source Document: {title}\nContent:\n{text}\n")

        print("=================================================\n")
        return "\n---\n".join(formatted_results)
    except Exception as e:
        # helps debugging retrieval failures
        print("[SEARCH ERROR]", e)
        return "I could not retrieve relevant company documentation."


# ---------------------------------------------------------
# FETCH DOCUMENT TOOL
# ---------------------------------------------------------
async def fetch_document_tool(
    ctx: Context,
    doc_id: Annotated[int, "ID of the document to retrieve"]
):
    """
    Returns full document content after permission verification.
    """

    user_data = await ctx.store.get("user_data")

    try:
        content = await DocsService.get_document_text(doc_id, user_data)
        return content
    except Exception:
        return "You do not have permission to access this document."


# ---------------------------------------------------------
# PERMISSIONS TOOL
# ---------------------------------------------------------
async def list_accessible_documents_tool(ctx: Context):
    """
    Lists documents accessible to the authenticated user.
    """

    user_dept_ids = await ctx.store.get("user_dept_ids") or []

    if not user_dept_ids:
        return "No departments are associated with your account."

    all_docs = []

    for dept_id in user_dept_ids:
        dept_docs = await DocsService.list_documents_with_access(dept_id)
        all_docs.extend(dept_docs)

    # deduplicate
    unique_docs = {doc["id"]: doc for doc in all_docs}.values()

    # sanitize output
    return [
        {
            "id": d["id"],
            "title": d["title"],
        }
        for d in unique_docs
    ]


# ---------------------------------------------------------
# TOOL REGISTRATION
# ---------------------------------------------------------
from llama_index.core.tools import FunctionTool
search_tool = FunctionTool.from_defaults(fn=search_documents_tool)
fetch_tool = FunctionTool.from_defaults(fn=fetch_document_tool)
list_tool = FunctionTool.from_defaults(fn=list_accessible_documents_tool)

def get_tools():
    return [search_tool, fetch_tool, list_tool]