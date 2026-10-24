"""Terminal driver: `uv run agent` for a REPL, or `uv run agent "your request"` for one turn."""

import json
import sys
import uuid

from dotenv import load_dotenv
from langchain_core.messages import AIMessage, HumanMessage, ToolMessage


def _text(message: AIMessage) -> str:
    if isinstance(message.content, str):
        return message.content
    return "".join(b.get("text", "") for b in message.content if isinstance(b, dict) and b.get("type") == "text")


def _run_turn(agent, thread_id: str, prompt: str) -> None:
    config = {"configurable": {"thread_id": thread_id}, "recursion_limit": 60}
    for update in agent.stream({"messages": [HumanMessage(prompt)]}, config, stream_mode="updates"):
        for node, payload in update.items():
            for message in payload.get("messages", []):
                if isinstance(message, AIMessage):
                    for call in message.tool_calls:
                        print(f"\n→ {call['name']} {json.dumps(call['args'])[:600]}")
                    if text := _text(message).strip():
                        print(f"\n{text}")
                elif isinstance(message, ToolMessage):
                    print(f"← {message.name}: {str(message.content)[:300]}")


def main() -> None:
    load_dotenv()
    from .graph import build_agent

    agent = build_agent()
    thread_id = str(uuid.uuid4())
    if len(sys.argv) > 1:
        _run_turn(agent, thread_id, " ".join(sys.argv[1:]))
        return
    print("Agent ready. Ctrl-D to exit.")
    while True:
        try:
            prompt = input("\n> ").strip()
        except (EOFError, KeyboardInterrupt):
            return
        if prompt:
            _run_turn(agent, thread_id, prompt)


if __name__ == "__main__":
    main()
