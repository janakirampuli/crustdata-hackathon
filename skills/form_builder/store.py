"""SQLite store shared by the agent tools and the form server. FORMS_DB overrides the path."""

import json
import os
import secrets
import sqlite3
import uuid
from collections.abc import Iterator
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path

from .schema import Survey

DEFAULT_DB = Path(__file__).resolve().parents[2] / "data" / "forms.db"

SCHEMA = """
CREATE TABLE IF NOT EXISTS surveys (
    id TEXT PRIMARY KEY,
    status TEXT NOT NULL DEFAULT 'draft',  -- draft | changes_requested | approved | closed
    spec TEXT NOT NULL,
    version INTEGER NOT NULL DEFAULT 1,
    feedback TEXT,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    approved_at TEXT
);
CREATE TABLE IF NOT EXISTS invites (
    token TEXT PRIMARY KEY,
    survey_id TEXT NOT NULL REFERENCES surveys(id),
    crustdata_person_id TEXT,
    target TEXT NOT NULL,
    created_at TEXT NOT NULL,
    opened_at TEXT,
    UNIQUE (survey_id, crustdata_person_id)
);
CREATE TABLE IF NOT EXISTS responses (
    token TEXT PRIMARY KEY REFERENCES invites(token),
    survey_id TEXT NOT NULL REFERENCES surveys(id),
    crustdata_person_id TEXT,
    answers TEXT NOT NULL,
    submitted_from_email TEXT,
    verified TEXT NOT NULL DEFAULT 'pending',  -- pending | ok | flag | fail
    reason TEXT,
    user_agent TEXT,
    submitted_at TEXT NOT NULL
);
"""


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


@contextmanager
def connect() -> Iterator[sqlite3.Connection]:
    """One short-lived connection per call: commits on success, always closes."""
    path = Path(os.environ.get("FORMS_DB", DEFAULT_DB))
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(path)
    conn.row_factory = sqlite3.Row
    try:
        conn.executescript(SCHEMA)
        with conn:
            yield conn
    finally:
        conn.close()


def _survey_row(row: sqlite3.Row | None) -> dict | None:
    if row is None:
        return None
    return {**dict(row), "spec": Survey.model_validate_json(row["spec"])}


def create_survey(survey: Survey) -> str:
    survey_id = uuid.uuid4().hex[:10]
    now = _now()
    with connect() as conn:
        conn.execute("INSERT INTO surveys (id, spec, created_at, updated_at) VALUES (?, ?, ?, ?)",
                     (survey_id, survey.model_dump_json(), now, now))
    return survey_id


def get_survey(survey_id: str) -> dict | None:
    with connect() as conn:
        return _survey_row(conn.execute("SELECT * FROM surveys WHERE id = ?", (survey_id,)).fetchone())


def list_surveys() -> list[dict]:
    with connect() as conn:
        rows = conn.execute("""
            SELECT s.*, (SELECT COUNT(*) FROM invites i WHERE i.survey_id = s.id) AS invites,
                   (SELECT COUNT(*) FROM responses r WHERE r.survey_id = s.id) AS responses
            FROM surveys s ORDER BY s.created_at DESC""").fetchall()
    return [{**_survey_row(r), "invites": r["invites"], "responses": r["responses"]} for r in rows]


def revise_survey(survey_id: str, survey: Survey) -> None:
    """Replaces the spec and sends it back to draft. Refused once invites exist."""
    with connect() as conn:
        if conn.execute("SELECT 1 FROM invites WHERE survey_id = ? LIMIT 1", (survey_id,)).fetchone():
            raise ValueError("survey already has invites; create a new survey instead")
        cur = conn.execute("""UPDATE surveys SET spec = ?, status = 'draft', version = version + 1,
                              approved_at = NULL, updated_at = ? WHERE id = ?""",
                           (survey.model_dump_json(), _now(), survey_id))
        if cur.rowcount == 0:
            raise KeyError(survey_id)


def set_status(survey_id: str, status: str, feedback: str | None = None) -> None:
    now = _now()
    with connect() as conn:
        conn.execute("""UPDATE surveys SET status = ?, feedback = ?, updated_at = ?,
                        approved_at = CASE WHEN ? = 'approved' THEN ? ELSE approved_at END WHERE id = ?""",
                     (status, feedback, now, status, now, survey_id))


def create_invites(survey_id: str, targets: list[dict]) -> list[dict]:
    """One unguessable token per target. Re-inviting the same person returns their existing token."""
    out = []
    with connect() as conn:
        for target in targets:
            person_id = target.get("crustdata_person_id")
            person_id = str(person_id) if person_id is not None else None
            existing = person_id and conn.execute(
                "SELECT token FROM invites WHERE survey_id = ? AND crustdata_person_id = ?",
                (survey_id, person_id)).fetchone()
            token = existing["token"] if existing else secrets.token_urlsafe(16)
            if not existing:
                conn.execute("INSERT INTO invites (token, survey_id, crustdata_person_id, target, created_at) "
                             "VALUES (?, ?, ?, ?, ?)", (token, survey_id, person_id, json.dumps(target), _now()))
            out.append({"token": token, "crustdata_person_id": person_id, "reused": bool(existing)})
    return out


def get_invite(token: str) -> dict | None:
    with connect() as conn:
        row = conn.execute("SELECT * FROM invites WHERE token = ?", (token,)).fetchone()
    return {**dict(row), "target": json.loads(row["target"])} if row else None


def mark_opened(token: str) -> None:
    with connect() as conn:
        conn.execute("UPDATE invites SET opened_at = ? WHERE token = ? AND opened_at IS NULL", (_now(), token))


def get_response(token: str) -> dict | None:
    with connect() as conn:
        row = conn.execute("SELECT * FROM responses WHERE token = ?", (token,)).fetchone()
    return {**dict(row), "answers": json.loads(row["answers"])} if row else None


def save_response(invite: dict, answers: dict, user_agent: str | None = None) -> bool:
    """Stores the first submission for a token. Returns False if the token was already used."""
    with connect() as conn:
        cur = conn.execute("""INSERT OR IGNORE INTO responses
                              (token, survey_id, crustdata_person_id, answers, user_agent, submitted_at)
                              VALUES (?, ?, ?, ?, ?, ?)""",
                           (invite["token"], invite["survey_id"], invite["crustdata_person_id"],
                            json.dumps(answers), user_agent, _now()))
    return cur.rowcount == 1


def list_responses(survey_id: str) -> list[dict]:
    with connect() as conn:
        rows = conn.execute("""SELECT r.*, i.target FROM responses r JOIN invites i USING (token)
                               WHERE r.survey_id = ? ORDER BY r.submitted_at""", (survey_id,)).fetchall()
    return [{**dict(r), "answers": json.loads(r["answers"]), "target": json.loads(r["target"])} for r in rows]


def invite_stats(survey_id: str) -> dict:
    with connect() as conn:
        row = conn.execute("""SELECT COUNT(*) AS invited, COUNT(i.opened_at) AS opened, COUNT(r.token) AS responded
                              FROM invites i LEFT JOIN responses r USING (token) WHERE i.survey_id = ?""",
                           (survey_id,)).fetchone()
    return dict(row)
