from pydantic import BaseModel

class ChatRequest(BaseModel):
    messages: list
    user: dict