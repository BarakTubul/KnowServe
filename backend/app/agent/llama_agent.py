_agent_instance = None

import os

def get_agent():
    global _agent_instance
    if _agent_instance is not None:
        return _agent_instance

    from llama_index.llms.openai import OpenAI
    from llama_index.core.memory import Memory, VectorMemoryBlock
    from llama_index.core.agent.workflow import FunctionAgent
    from app.core.vector_store import get_embed_model

    # 1. Setup LLM and Embeddings
    llm = OpenAI(
        model="gpt-4o-mini",
        temperature=0
    )

    # Reuse the global singleton embed model to prevent disk reload
    embed_model = get_embed_model()

    # 2. Reuse your existing Persistent Client for Memory
    from app.core.chroma_client import get_chroma_client
    client = get_chroma_client()
    memory_collection = client.get_or_create_collection("chat_history")
    
    from llama_index.vector_stores.chroma import ChromaVectorStore
    vector_store = ChromaVectorStore(chroma_collection=memory_collection)

    # 3. Configure Optimized Memory
    memory = Memory.from_defaults(
        token_limit=3000,
        memory_blocks=[
            VectorMemoryBlock(
                name="long_term_chat_memory",
                vector_store=vector_store,
                embed_model=embed_model,
                priority=1 
            )
        ]
    )

    from app.agent.llama_tools import get_tools

    # 4. Initialize the Agent
    _agent_instance = FunctionAgent(
        name="KnowServe_Agent",
        llm=llm,
        tools=get_tools(),
        memory=memory,
        system_prompt = (
        "You are KnowServe, a secure internal company knowledge assistant.\n"
        "The user is already authenticated by the backend.\n"
        "You are NOT responsible for determining permissions.\n\n"

        "SECURITY RULES:\n"
        "- Never ask the user what department they belong to.\n"
        "- Never guess what documents they can access.\n"
        "- You do not know permissions yourself.\n"
        "- When asked what documents the user can access, ALWAYS call list_accessible_documents_tool.\n"
        "- When asked about document content, use the search_documents_tool.\n"
        "- When a specific document is requested, use fetch_document_tool.\n"
        "- The backend authorization service is the single source of truth.\n"
        "- IF a user asks for information that is not in the documents you are allowed to retrieve, answer generally if you can, but EXPLICITLY state: 'I can only provide general information as I do not have access to restricted company documents regarding this topic.'\n\n"

        "KNOWLEDGE & CITATION RULES:\n"
        "- You do NOT know any company information yourself.\n"
        "- All company policies, procedures, benefits, and guidelines exist ONLY inside documents.\n"
        "- If a user asks any question about company rules, benefits, procedures, policies, HR, engineering practices, or internal processes, you MUST use search_documents_tool before answering.\n"
        "- You are forbidden from answering from general knowledge.\n"
        "- If you have not searched documents, you do not know the answer.\n"
        "- ALWAYS cite the exact 'Document Title' when providing information retrieved from the search tool (e.g., 'According to the Employee Handbook...').\n"
        )
    )
    return _agent_instance