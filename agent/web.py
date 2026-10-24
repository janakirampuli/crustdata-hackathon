"""Chat UI: `uv run web` serves the chat at /chat and the form pages (/surveys, /s/<token>) on one port.

POST /api/chat streams one agent turn as server-sent events:
  {"type": "text", "text": delta} | {"type": "tool_call", id, name, args} | {"type": "tool_result", id, name, content}
  | {"type": "error", "message"} | {"type": "done"}
GET /api/threads/<id> replays a thread's history as the same events (minus text deltas: one event per text block).
"""

import json
import os
import sqlite3
import threading
from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.responses import HTMLResponse, RedirectResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from langchain_core.messages import AIMessage, AIMessageChunk, HumanMessage, ToolMessage
from langgraph.checkpoint.sqlite import SqliteSaver
from pydantic import BaseModel, Field

from skills.form_builder import store
from skills.form_builder.server import app as forms_app, make_templates

from .cli import _text

HERE = Path(__file__).parent
DEFAULT_DB = Path(__file__).resolve().parents[1] / "data" / "agent.db"

app = FastAPI(title="Research agent")
app.mount("/agent-static", StaticFiles(directory=HERE / "static"), name="agent-static")
templates = make_templates(HERE / "templates")
_agent = None
_agent_lock = threading.Lock()


def _checkpointer() -> SqliteSaver:
    """Conversations survive server restarts. AGENT_DB overrides the path."""
    path = Path(os.environ.get("AGENT_DB", DEFAULT_DB))
    path.parent.mkdir(parents=True, exist_ok=True)
    # Turns stream from a threadpool; SqliteSaver serializes access with its own lock.
    return SqliteSaver(sqlite3.connect(path, check_same_thread=False))


def get_agent():
    global _agent
    with _agent_lock:
        if _agent is None:
            from .graph import build_agent

            _agent = build_agent(checkpointer=_checkpointer())
    return _agent


def _tool_call(call: dict) -> dict:
    return {"type": "tool_call", "id": call["id"], "name": call["name"], "args": call["args"]}


def _tool_result(message: ToolMessage) -> dict:
    try:
        content = json.loads(message.content)
    except (TypeError, ValueError):
        content = message.content
    return {"type": "tool_result", "id": message.tool_call_id, "name": message.name, "content": content}


def _search_result(block: dict) -> dict:
    content = block.get("content")
    if isinstance(content, dict):  # web_search_tool_result_error
        return {"error": content.get("error_code", "search_failed")}
    return {"results": [{"title": r.get("title"), "url": r.get("url"), "page_age": r.get("page_age")}
                        for r in content or [] if isinstance(r, dict)]}


def _server_event(block: dict) -> dict | None:
    """Server tools (web search) run inside the model call, so they live in the message content, not tool_calls."""
    if block.get("type") == "server_tool_use":
        args = block.get("input") or {}
        if not args and block.get("partial_json"):  # a streamed block keeps its input as the raw JSON string
            try:
                args = json.loads(block["partial_json"])
            except ValueError:
                pass
        return {"type": "tool_call", "id": block["id"], "name": block["name"], "args": args}
    if block.get("type") == "web_search_tool_result":
        return {"type": "tool_result", "id": block["tool_use_id"], "name": "web_search", "content": _search_result(block)}
    return None


def _message_events(message: AIMessage) -> list[dict]:
    """A finished model message as events, keeping server-tool cards in place between its text blocks."""
    events, text = [], ""
    blocks = message.content if isinstance(message.content, list) else [{"type": "text", "text": message.content}]
    for block in blocks:
        if not isinstance(block, dict):
            continue
        if block.get("type") == "text":
            text += block.get("text", "")
        elif event := _server_event(block):
            if text:
                events.append({"type": "text", "text": text})
                text = ""
            events.append(event)
    if text:
        events.append({"type": "text", "text": text})
    return events + [_tool_call(c) for c in message.tool_calls]


def history_events(messages: list) -> list[dict]:
    events = []
    for message in messages:
        if isinstance(message, HumanMessage):
            events.append({"type": "user", "text": _text(message)})
        elif isinstance(message, AIMessage):
            events.extend(_message_events(message))
        elif isinstance(message, ToolMessage):
            events.append(_tool_result(message))
    return events


def _sse(event: dict) -> str:
    return f"data: {json.dumps(event, default=str)}\n\n"


def _turn_events(thread_id: str, message: str):
    config = {"configurable": {"thread_id": thread_id}, "recursion_limit": 60}
    streamed = set()
    searches = {}  # (message id, block index) -> server tool call whose input JSON is still streaming
    results = set()  # server tool results already sent
    try:
        for mode, chunk in get_agent().stream({"messages": [HumanMessage(message)]}, config,
                                              stream_mode=["messages", "updates"]):
            if mode == "messages":
                token, meta = chunk
                if not isinstance(token, AIMessageChunk) or meta.get("langgraph_node") != "agent":
                    continue
                if text := _text(token):
                    streamed.add(token.id)
                    yield _sse({"type": "text", "text": text})
                for block in token.content if isinstance(token.content, list) else []:
                    key = (token.id, block.get("index"))
                    if block.get("type") == "server_tool_use":
                        searches[key] = {"id": block["id"], "name": block["name"], "json": ""}
                    elif block.get("type") == "input_json_delta" and key in searches:
                        call = searches[key]
                        call["json"] += block.get("partial_json", "")
                        try:
                            args = json.loads(call["json"])
                        except ValueError:
                            continue
                        del searches[key]
                        yield _sse({"type": "tool_call", "id": call["id"], "name": call["name"], "args": args})
                    elif event := _server_event(block):
                        streamed.add(token.id)
                        if event["type"] == "tool_result":
                            results.add(event["id"])
                        yield _sse(event)
                continue
            for payload in chunk.values():
                for msg in (payload or {}).get("messages", []):
                    if isinstance(msg, AIMessage):
                        # A model call that didn't stream gets replayed whole. One that did may still be missing
                        # its web search results, which don't always arrive as stream chunks.
                        if msg.id in streamed:
                            events = [e for e in _message_events(msg) if e["type"] == "tool_result" and e["id"] not in results]
                            events += [_tool_call(c) for c in msg.tool_calls]
                        else:
                            events = _message_events(msg)
                        for event in events:
                            yield _sse(event)
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
def chat_page(request: Request):
    return templates.TemplateResponse(request, "chat.html")


@app.post("/api/chat")
def chat(request: ChatRequest):
    return StreamingResponse(_turn_events(request.thread_id, request.message), media_type="text/event-stream",
                             headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})


@app.get("/api/surveys/{survey_id}/canvas", response_class=HTMLResponse)
def survey_canvas(request: Request, survey_id: str):
    """In-chat approval canvas. Its buttons post to the form server's approve / request-changes routes."""
    row = store.get_survey(survey_id)
    if row is None:
        return HTMLResponse('<p class="cap">This survey no longer exists.</p>', status_code=404)
    return templates.TemplateResponse(request, "_survey_canvas.html", {"row": row, "survey": row["spec"]})


@app.get("/api/threads")
def threads(limit: int = 30):
    """Saved conversations, most recent first, titled by their first message."""
    agent = get_agent()
    saver = agent.checkpointer
    if not isinstance(saver, SqliteSaver):
        return {"threads": []}
    saver.setup()
    with saver.lock:
        rows = saver.conn.execute("""SELECT thread_id FROM checkpoints WHERE checkpoint_ns = ''
                                     GROUP BY thread_id ORDER BY MAX(checkpoint_id) DESC LIMIT ?""", (limit,)).fetchall()
    out = []
    for (thread_id,) in rows:
        state = agent.get_state({"configurable": {"thread_id": thread_id}})
        asks = [_text(m) for m in state.values.get("messages", []) if isinstance(m, HumanMessage)]
        if asks:
            out.append({"id": thread_id, "title": asks[0][:90], "turns": len(asks), "updated_at": state.created_at})
    return {"threads": out}


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
    from skills.campaign import service

    service.start_scheduler()
    uvicorn.run(app, host=os.environ.get("FORMS_HOST", "127.0.0.1"), port=int(os.environ.get("FORMS_PORT", "8000")))


if __name__ == "__main__":
    main()
