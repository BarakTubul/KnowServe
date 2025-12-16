import pytest
from app.agent.tools import fetch_document

@pytest.mark.asyncio
async def test_fetch_document_real_flow():

    user = {
    "user_id": 8,
    "role": "EMPLOYEE",
    "departments": [2],
    }

    doc_id = 1

    result = await fetch_document.ainvoke({"doc_id": doc_id, "user": user})

    # 4️⃣ Assertions
    assert result["id"] == doc_id
    assert result["title"] == "Employee Handbook"
    

    print("\nExtracted text preview:")
    print(result["content"][:200])
