import pytest
from unittest.mock import patch, MagicMock
from langchain_core.messages import AIMessage, HumanMessage

from app.agent.graph import graph


# ---------------------------------------------------------
# 1. Test: Agent produces NO tool call → goes to final_answer
# ---------------------------------------------------------
def test_graph_final_answer_path(mocker):

    # Mock output of LLM
    mock_ai = AIMessage(content="Hello from KnowServe!")

    # Patch only the `invoke` method of the llm object
    mocker.patch("app.agent.graph.llm.invoke", return_value=mock_ai)

    # Execute graph
    result = graph.invoke({
        "messages": [HumanMessage(content="Hi")],
        "user": {"id": 1}
    })

    final = result["messages"][-1]
    assert final.content == "Hello from KnowServe!"

# ---------------------------------------------------------
# 2. Test: Agent requests tool → Should route to tool node
# ---------------------------------------------------------
def test_graph_tool_call_path():

    # Fake LLM output requesting a tool call
    mock_ai = AIMessage(
        content="",
        tool_calls=[{"name": "search_documents", "args": {"query": "policy"}}]
    )

    # Fake tool result
    fake_tool_output = AIMessage(content="Tool response: Found docs")

    # Patch LLM and tools
    with patch("app.agent.graph.llm.invoke", return_value=mock_ai):
        with patch("app.agent.tools.search_documents.invoke", return_value=fake_tool_output):
            result = graph.invoke({"messages": [HumanMessage(content="Find policy")], "user": {"id": 1}})

    final = result["messages"][-1]
    assert "Found docs" in final.content


# ---------------------------------------------------------
# 3. Test: Tool output loops back to agent
# ---------------------------------------------------------
def test_graph_tool_then_agent():

    # Step 1: LLM outputs tool call
    mock_ai_toolcall = AIMessage(
        content="",
        tool_calls=[{"name": "summarize_document", "args": {"doc_id": 123}}]
    )

    # Step 2: tool returns output
    mock_tool_output = AIMessage(content="Summary of doc")

    # Step 3: LLM receives tool result and outputs final answer
    mock_ai_final = AIMessage(content="Here is the summary: Summary of doc")

    # Patch the sequence of responses
    with patch("app.agent.graph.llm.invoke", side_effect=[mock_ai_toolcall, mock_ai_final]):
        with patch("app.agent.tools.summarize_document.invoke", return_value=mock_tool_output):
            result = graph.invoke({
                "messages": [HumanMessage(content="Summarize doc 123")],
                "user": {"id": 1}
            })

    final = result["messages"][-1].content
    assert "Summary of doc" in final


# ---------------------------------------------------------
# 4. Test: Permissions logic inside tools (example)
# ---------------------------------------------------------
def test_permission_blocked():

    # Mock the tool to raise a permission error
    with patch("app.agent.tools.fetch_document.invoke", side_effect=PermissionError("Not allowed")):
        
        # Mock LLM to call fetch_document
        mock_ai = AIMessage(
            content="",
            tool_calls=[{"name": "fetch_document", "args": {"doc_id": 555}}]
        )

        with patch("app.agent.graph.llm.invoke", return_value=mock_ai):

            with pytest.raises(PermissionError):
                graph.invoke({
                    "messages": [HumanMessage(content="Get doc 555")],
                    "user": {"id": 99}
                })
