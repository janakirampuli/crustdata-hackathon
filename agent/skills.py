"""Skill discovery. A skill is a folder under skills/ with a SKILL.md (frontmatter + knowledge) and an
optional tools.py exposing TOOLS. The SKILL.md body goes into the system prompt; TOOLS are bound to the model.
"""

import importlib
from dataclasses import dataclass, field
from pathlib import Path

from langchain_core.tools import BaseTool

SKILLS_DIR = Path(__file__).resolve().parent.parent / "skills"


@dataclass
class Skill:
    name: str
    description: str
    instructions: str
    tools: list[BaseTool | dict] = field(default_factory=list)  # dicts are Anthropic server tools


def _parse(skill_md: Path) -> tuple[dict[str, str], str]:
    text = skill_md.read_text()
    if not text.startswith("---"):
        return {}, text
    _, header, body = text.split("---", 2)
    meta = {}
    for line in header.strip().splitlines():
        key, _, value = line.partition(":")
        meta[key.strip()] = value.strip()
    return meta, body.strip()


def load_skills(names: list[str] | None = None) -> list[Skill]:
    """Loads enabled skills (or exactly ``names`` when given), sorted by folder name."""
    skills = []
    for folder in sorted(p for p in SKILLS_DIR.iterdir() if (p / "SKILL.md").is_file()):
        meta, body = _parse(folder / "SKILL.md")
        name = meta.get("name", folder.name)
        if names is not None and name not in names and folder.name not in names:
            continue
        if names is None and meta.get("enabled", "true").lower() == "false":
            continue
        tools = []
        if (folder / "tools.py").is_file():
            tools = list(importlib.import_module(f"skills.{folder.name}.tools").TOOLS)
        skills.append(Skill(name, meta.get("description", ""), body, tools))
    return skills
