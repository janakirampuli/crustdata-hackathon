"""Chat UI: `uv run web` serves the chat at /chat and the form pages (/surveys, /s/<token>) on one port.

POST /api/chat streams one agent turn as server-sent events:
  {"type": "text", "text": delta} | {"type": "tool_call", id, name, args} | {"type": "tool_result", id, name, content}
  | {"type": "error", "message"} | {"type": "done"}
GET /api/threads/<id> replays a thread's history as the same events (minus text deltas: one event per text block).
"""

import json
import os
import threading
from pathlib import Path

from fastapi import FastAPI
from fastapi.responses import FileResponse, RedirectResponse, StreamingResponse
from langchain_core.messages import AIMessage, AIMessageChunk, HumanMessage, ToolMessage
from pydantic import BaseModel, Field

from skills.form_builder.server import app as forms_app

from .cli import _text

STATIC = Path(__file__).parent / "static"

app = FastAPI(title="Research agent")
_agent = None
_agent_lock = threading.Lock()


def get_agent():
    global _agent
    with _agent_lock:
        if _agent is None:
            from .graph import build_agent

            _agent = build_agent()
    return _agent


def _tool_call(call: dict) -> dict:
    return {"type": "tool_call", "id": call["id"], "name": call["name"], "args": call["args"]}


def _tool_result(message: ToolMessage) -> dict:
    try:
        content = json.loads(message.content)
    except (TypeError, ValueError):
        content = message.content
    return {"type": "tool_result", "id": message.tool_call_id, "name": message.name, "content": content}


def history_events(messages: list) -> list[dict]:
    events = []
    for message in messages:
        if isinstance(message, HumanMessage):
            events.append({"type": "user", "text": _text(message)})
        elif isinstance(message, AIMessage):
            if text := _text(message):
                events.append({"type": "text", "text": text})
            events.extend(_tool_call(c) for c in message.tool_calls)
        elif isinstance(message, ToolMessage):
            events.append(_tool_result(message))
    return events


def _sse(event: dict) -> str:
    return f"data: {json.dumps(event, default=str)}\n\n"


def _turn_events(thread_id: str, message: str):
    config = {"configurable": {"thread_id": thread_id}, "recursion_limit": 60}
    streamed = set()
    try:
        for mode, chunk in get_agent().stream({"messages": [HumanMessage(message)]}, config,
                                              stream_mode=["messages", "updates"]):
            if mode == "messages":
                token, meta = chunk
                if isinstance(token, AIMessageChunk) and meta.get("langgraph_node") == "agent":
                    if text := _text(token):
                        streamed.add(token.id)
                        yield _sse({"type": "text", "text": text})
                continue
            for payload in chunk.values():
                for msg in (payload or {}).get("messages", []):
                    if isinstance(msg, AIMessage):
                        # Fallback for a model call that didn't stream tokens.
                        if msg.id not in streamed and (text := _text(msg)):
                            yield _sse({"type": "text", "text": text})
                        for call in msg.tool_calls:
                            yield _sse(_tool_call(call))
                    elif isinstance(msg, ToolMessage):
                        yield _sse(_tool_result(msg))
    except Exception as e:  # surface to the UI instead of a silently dropped stream
        yield _sse({"type": "error", "message": f"{type(e).__name__}: {e}"})
    yield _sse({"type": "done"})


class ChatRequest(BaseModel):
    thread_id: str = Field(min_length=1, max_length=100)
    message: str = Field(min_length=1, max_length=20000)


@app.get("/", include_in_schema=False)
def root():
    return RedirectResponse("/chat")


@app.get("/chat", include_in_schema=False)
def chat_page():
    return FileResponse(STATIC / "chat.html")


@app.post("/api/chat")
def chat(request: ChatRequest):
    return StreamingResponse(_turn_events(request.thread_id, request.message), media_type="text/event-stream",
                             headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})


@app.get("/api/threads/{thread_id}")
def thread(thread_id: str):
    state = get_agent().get_state({"configurable": {"thread_id": thread_id}})
    return {"events": history_events(state.values.get("messages", []))}


# Last, so the routes above win; the form server keeps its own paths (and FORMS_BASE_URL stays valid).
app.mount("/", forms_app)


def main() -> None:
    import uvicorn
    from dotenv import load_dotenv

    load_dotenv()
    get_agent()
    uvicorn.run(app, host=os.environ.get("FORMS_HOST", "127.0.0.1"), port=int(os.environ.get("FORMS_PORT", "8000")))


if __name__ == "__main__":
    main()
