# services/chat_service.py

from agent.graph import graph

class ChatService:

    def run_query(self, messages: list, user: dict):
        """
        Runs the KnowServe LangGraph agent using the provided messages and user.
        This method is the single entry point for all chat interactions.
        """
        payload = {
            "messages": messages,
            "user": user
        }

        result = graph.invoke(payload)

        return result["messages"]

    async def run_query_stream(self, messages: list, user: dict):
        """
        Streaming version — yields tokens or message fragments.
        """
        payload = {
            "messages": messages,
            "user": user
        }

        async for step in graph.astream(payload):
            msg = step["messages"][-1]
            if msg.get("content"):
                yield msg["content"]
