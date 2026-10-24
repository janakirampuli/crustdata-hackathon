"""The agent backbone: one model node and one tool node, looping until the model stops calling tools."""

import os
from datetime import date
from typing import Annotated, TypedDict

from langchain_anthropic import ChatAnthropic
from langchain_core.messages import AnyMessage, SystemMessage
from langgraph.checkpoint.memory import InMemorySaver
from langgraph.graph import END, START, StateGraph
from langgraph.graph.message import add_messages
from langgraph.prebuilt import ToolNode, tools_condition

from .skills import Skill, load_skills

BASE_PROMPT = """You are a research operations agent. You replace a B2B survey and market-research firm: given a \
research question and the kind of professional to hear from, you decide exactly who qualifies, find them, and \
return work that a client can trust without a human in between.

Principles:
- Target first. Decide who qualifies before contacting anyone; 20 verified respondents beat 200 unverified ones.
- Every claim about a person must come from a tool result. Never invent people, titles, employers or emails.
- Spend credits deliberately: small pages first, check total_count, then widen.
- When a tool reports warnings or an error, fix the call and retry instead of guessing.
- Be concise with the user. Show the filters you used and why each person qualifies.

Workflow for a new study: confirmed research brief (briefing skill; skipped when the user asks for a draft directly) → \
survey draft and human approval (form-builder skill) → verified targets and business emails (crustdata skill) → one invite link per target."""


class State(TypedDict):
    messages: Annotated[list[AnyMessage], add_messages]


def system_prompt(skills: list[Skill]) -> str:
    sections = [BASE_PROMPT, f"Today's date: {date.today().isoformat()}"]
    for skill in skills:
        sections.append(f"<skill name=\"{skill.name}\">\n{skill.instructions}\n</skill>")
    return "\n\n".join(sections)


def _server_tool(spec: dict, model: str) -> dict:
    """Pins an Anthropic server tool to a version the model accepts."""
    if spec["type"] == "web_search":
        # Haiku 5.5 rejects the dynamic-filtering version's calls with invalid_tool_input; it takes the basic one.
        version = "web_search_20250305" if "haiku" in model else "web_search_20260209"
        return {**spec, "type": version}
    return spec


def build_agent(skill_names: list[str] | None = None, model: str | None = None, checkpointer=None):
    skills = load_skills(skill_names)
    model = model or os.environ.get("AGENT_MODEL")
    if not model:
        raise RuntimeError("AGENT_MODEL is not set; see .env.example")
    tools = [t for s in skills for t in s.tools if not isinstance(t, dict)]
    server_tools = [_server_tool(t, model) for s in skills for t in s.tools if isinstance(t, dict)]
    llm = ChatAnthropic(model=model, max_tokens=16000)
    llm = llm.bind_tools(tools + server_tools) if tools or server_tools else llm
    # One cached system block: skills are static for the life of the agent.
    system = SystemMessage(content=[{
        "type": "text",
        "text": system_prompt(skills),
        "cache_control": {"type": "ephemeral"},
    }])

    def call_model(state: State) -> dict:
        # Top-level cache_control moves a breakpoint to the end of the conversation on every call, so each tool-loop
        # step and each new turn reads the earlier prefix from cache and only writes what was appended.
        return {"messages": [llm.invoke([system, *state["messages"]], cache_control={"type": "ephemeral"})]}

    graph = StateGraph(State)
    graph.add_node("agent", call_model)
    graph.add_edge(START, "agent")
    if tools:
        graph.add_node("tools", ToolNode(tools))
        graph.add_conditional_edges("agent", tools_condition, {"tools": "tools", END: END})
        graph.add_edge("tools", "agent")
    else:
        graph.add_edge("agent", END)
    return graph.compile(checkpointer=checkpointer if checkpointer is not None else InMemorySaver())
