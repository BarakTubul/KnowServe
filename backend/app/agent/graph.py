# graph.py

from langchain_core.messages import AIMessage
from langgraph.graph import StateGraph, START, END, MessagesState
from langgraph.prebuilt import ToolNode
from langgraph.checkpoint.memory import MemorySaver
from langchain_ollama import ChatOllama

from app.agent.tools import (
    search_documents,
    summarize_document,
    fetch_document,
    list_user_departments,
)

# =====================================
# 1. OLLAMA LLM
# =====================================
llm = ChatOllama(model="llama3", temperature=0)



# =====================================
# 2. AGENT NODE
# =====================================
def agent_node(state: MessagesState):
    system_msg = {
        "role": "system",
        "content": (
            "You are KnowServe, a secure internal assistant. "
            "Use tools when needed. "
            "Never reveal information outside the user's access permissions."
        )
    }

    result = llm.invoke([system_msg] + state["messages"])
    return {"messages": [result]}


# =====================================
# 3. FINAL ANSWER NODE
# =====================================
def final_answer_node(state: MessagesState):
    """
    Handles the final message before sending to the client.
    This is where we can:
    - filter output
    - format the final answer
    - log interactions
    - attach metadata
    """
    last = state["messages"][-1]

    # Example post-processing:
    cleaned = last.content.strip()

    # Wrap as an AIMessage to keep consistency
    return {"messages": AIMessage(content=cleaned)}


# =====================================
# 4. SHOULD CONTINUE DECISION
# =====================================
def should_continue(state: MessagesState):
    last_msg = state["messages"][-1]

    if not isinstance(last_msg, AIMessage):
        return "final_answer"

    if not last_msg.tool_calls:
        return "final_answer"

    return "tools"


# =====================================
# 5. TOOL NODE
# =====================================
tool_node = ToolNode([
    search_documents,
    summarize_document,
    fetch_document,
    list_user_departments
])


# =====================================
# 6. BUILD GRAPH
# =====================================
builder = StateGraph(MessagesState)

builder.add_node("agent", agent_node)
builder.add_node("tools", tool_node)
builder.add_node("final_answer", final_answer_node)

# Start → agent
builder.add_edge(START, "agent")

# Agent → decision
builder.add_conditional_edges(
    "agent",
    should_continue,
    {
        "tools": "tools",
        "final_answer": "final_answer"
    }
)

# Tools → agent loop
builder.add_edge("tools", "agent")

# Final answer ends workflow
builder.add_edge("final_answer", END)

graph = builder.compile(checkpointer=MemorySaver())

