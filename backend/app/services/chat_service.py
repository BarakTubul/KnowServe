from app.agent.llama_agent import get_agent
from llama_index.core.agent.workflow import AgentStream,ToolCallResult
from llama_index.core.llms import ChatMessage as LlamaChatMessage, MessageRole
from app.pydantic_schemas.chat_schema import ChatMessage
from typing import List
import json
import time


class ChatService:

    @staticmethod
    async def get_streaming_chat_response(messages: List[ChatMessage], user: dict):

        start_time = time.time()
        first_token_time = None
        tool_start_times = {}

        latest_message = messages[-1].content
        
        # Limit short-term memory to the last 10 messages to prevent token limits
        MAX_HISTORY_MESSAGES = 10
        recent_messages = messages[-(MAX_HISTORY_MESSAGES + 1):-1] if len(messages) > 1 else []

        # Build short-term chat history from frontend context
        chat_history = []
        for msg in recent_messages:
            role = MessageRole.USER if msg.role == 'user' else MessageRole.ASSISTANT
            chat_history.append(LlamaChatMessage(role=role, content=msg.content))

        # Start agent run
        agent = get_agent()
        handler = agent.run(
            user_msg=latest_message,
            chat_history=chat_history,
            streaming=True,
        )

        dept_id = user.get("department_id")

        # normalize to list because tools expect list[int]
        dept_ids = [dept_id] if dept_id is not None else []

        await handler.ctx.store.set("user_dept_ids", dept_ids)
        await handler.ctx.store.set("user_data", user)

        async for event in handler.stream_events():

            # token streaming
            if isinstance(event, AgentStream):
                if first_token_time is None:
                    first_token_time = time.time()
                    print(f"\n[PROFILER] Time to First Token (TTFT): {first_token_time - start_time:.3f}s")
                if event.delta:
                    yield f"data: {json.dumps({'type': 'token', 'content': event.delta})}\n\n"

            # tool call started
            if hasattr(event, "tool_name") and not isinstance(event, ToolCallResult):
                tool_start_times[event.tool_name] = time.time()
                print(f"\n[AGENT] Calling tool: {event.tool_name}")

            # tool result (THE IMPORTANT PART)
            if isinstance(event, ToolCallResult):
                tool_duration = time.time() - tool_start_times.get(event.tool_name, time.time())
                print(f"\n[PROFILER] Tool {event.tool_name} took {tool_duration:.3f}s")
                print("\n========== TOOL RESULT ==========")
                print("Tool:", event.tool_name)
                print("Input:", event.tool_kwargs)
                print("Output:", event.tool_output)
                print("=================================\n")

                yield f"data: {json.dumps({'type': 'tool', 'tool': event.tool_name})}\n\n"
        try:
            print("DEBUG: Waiting for handler to complete to catch final result/errors...")
            final_result = await handler
            print(f"DEBUG: Final handler result: {final_result}")
        except Exception as e:
            print(f"🚨 HANDLER CRASHED WITH ERROR: {e}")
            raise e

        total_time = time.time() - start_time
        print(f"\n[PROFILER] Total Chat Processing Time: {total_time:.3f}s")

    @staticmethod
    async def clear_chat_history(user_id: str):
        agent = get_agent()
        agent.memory.reset()
        return {"message": "Chat history cleared."}