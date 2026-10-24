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

from .schema import Audience, CampaignConfig, Survey

DEFAULT_DB = Path(__file__).resolve().parents[2] / "data" / "forms.db"

SCHEMA = """
CREATE TABLE IF NOT EXISTS surveys (
    id TEXT PRIMARY KEY,
    status TEXT NOT NULL DEFAULT 'draft',  -- draft | changes_requested | approved | fielding | closed
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
CREATE TABLE IF NOT EXISTS events (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    survey_id TEXT NOT NULL,
    token TEXT,
    type TEXT NOT NULL,  -- launched | invited | followup | opened | responded | opted_out | closed | config | insights
    detail TEXT,
    at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS outbox (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    survey_id TEXT NOT NULL,
    token TEXT,
    kind TEXT NOT NULL,  -- invite | followup
    to_email TEXT,
    subject TEXT NOT NULL,
    body TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'logged',  -- logged (EMAIL_MODE=log) | sent | blocked | failed
    created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS insights (
    survey_id TEXT PRIMARY KEY,
    stats TEXT NOT NULL,
    report TEXT NOT NULL,
    model TEXT,
    generated_at TEXT NOT NULL
);
"""
# Columns added after the first release; added in place so existing databases keep their data.
COLUMNS = {
    "surveys": {"config": "TEXT", "audience": "TEXT", "launched_at": "TEXT", "closes_at": "TEXT",
                "closed_at": "TEXT", "close_reason": "TEXT", "brief": "TEXT",
                "email_preview": "TEXT"},  # JSON {samples, emails}: the invite template filled for a few real people
    "outbox": {"provider_id": "TEXT", "error": "TEXT"},
    "invites": {"email": "TEXT", "state": "TEXT NOT NULL DEFAULT 'created'", "invited_at": "TEXT",
                "last_contacted_at": "TEXT", "followups_sent": "INTEGER NOT NULL DEFAULT 0", "opted_out_at": "TEXT"},
}


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
        _migrate(conn)
        with conn:
            yield conn
    finally:
        conn.close()


def _migrate(conn: sqlite3.Connection) -> None:
    for table, columns in COLUMNS.items():
        have = {r[1] for r in conn.execute(f"PRAGMA table_info({table})")}
        for name, decl in columns.items():
            if name not in have:
                conn.execute(f"ALTER TABLE {table} ADD COLUMN {name} {decl}")
    conn.commit()


def _survey_row(row: sqlite3.Row | None) -> dict | None:
    if row is None:
        return None
    d = dict(row)
    return {**d, "spec": Survey.model_validate_json(d["spec"]),
            "config": CampaignConfig.model_validate_json(d["config"]) if d.get("config") else CampaignConfig(),
            "audience": Audience.model_validate_json(d["audience"]) if d.get("audience") else None,
            "email_preview": json.loads(d["email_preview"]) if d.get("email_preview") else None}


def create_survey(survey: Survey, brief: str | None = None) -> str:
    survey_id = uuid.uuid4().hex[:10]
    now = _now()
    with connect() as conn:
        conn.execute("INSERT INTO surveys (id, spec, brief, created_at, updated_at) VALUES (?, ?, ?, ?, ?)",
                     (survey_id, survey.model_dump_json(), brief, now, now))
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


def revise_survey(survey_id: str, survey: Survey, brief: str | None = None) -> None:
    """Replaces the spec (and the brief, when given) and sends it back to draft. Refused once invites exist."""
    with connect() as conn:
        if conn.execute("SELECT 1 FROM invites WHERE survey_id = ? LIMIT 1", (survey_id,)).fetchone():
            raise ValueError("survey already has invites; create a new survey instead")
        cur = conn.execute("""UPDATE surveys SET spec = ?, brief = COALESCE(?, brief), status = 'draft',
                              version = version + 1, approved_at = NULL, updated_at = ? WHERE id = ?""",
                           (survey.model_dump_json(), brief, _now(), survey_id))
        if cur.rowcount == 0:
            raise KeyError(survey_id)


def set_email_preview(survey_id: str, preview: dict | None) -> None:
    with connect() as conn:
        conn.execute("UPDATE surveys SET email_preview = ? WHERE id = ?",
                     (json.dumps(preview) if preview else None, survey_id))


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


def mark_opened(token: str) -> bool:
    """Records the first open. Returns True only for that first open."""
    with connect() as conn:
        cur = conn.execute("""UPDATE invites SET opened_at = ?,
                              state = CASE WHEN state IN ('created', 'invited') THEN 'opened' ELSE state END
                              WHERE token = ? AND opened_at IS NULL""", (_now(), token))
    return cur.rowcount == 1


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
        if cur.rowcount == 1:
            conn.execute("UPDATE invites SET state = 'responded' WHERE token = ?", (invite["token"],))
    return cur.rowcount == 1


def list_responses(survey_id: str) -> list[dict]:
    with connect() as conn:
        rows = conn.execute("""SELECT r.*, i.target FROM responses r JOIN invites i USING (token)
                               WHERE r.survey_id = ? ORDER BY r.submitted_at""", (survey_id,)).fetchall()
    return [{**dict(r), "answers": json.loads(r["answers"]), "target": json.loads(r["target"])} for r in rows]


def invite_stats(survey_id: str) -> dict:
    with connect() as conn:
        row = conn.execute("""SELECT COUNT(*) AS invited, COUNT(i.opened_at) AS opened, COUNT(r.token) AS responded,
                                     COUNT(i.opted_out_at) AS opted_out
                              FROM invites i LEFT JOIN responses r USING (token) WHERE i.survey_id = ?""",
                           (survey_id,)).fetchone()
    return dict(row)


# ---- campaign ----

def set_config(survey_id: str, config: CampaignConfig) -> None:
    with connect() as conn:
        row = conn.execute("SELECT launched_at FROM surveys WHERE id = ?", (survey_id,)).fetchone()
        if row is None:
            raise KeyError(survey_id)
        # The deadline follows the config while fielding, counted from launch.
        closes_at = _plus_minutes(row["launched_at"], config.deadline_minutes) if row["launched_at"] else None
        conn.execute("UPDATE surveys SET config = ?, closes_at = COALESCE(?, closes_at), updated_at = ? WHERE id = ?",
                     (config.model_dump_json(), closes_at, _now(), survey_id))


def set_audience(survey_id: str, audience: Audience) -> None:
    with connect() as conn:
        conn.execute("UPDATE surveys SET audience = ?, updated_at = ? WHERE id = ?",
                     (audience.model_dump_json(), _now(), survey_id))


def _plus_minutes(iso: str, minutes: int) -> str:
    from datetime import timedelta

    return (datetime.fromisoformat(iso) + timedelta(minutes=minutes)).isoformat(timespec="seconds")


def mark_launched(survey_id: str, deadline_minutes: int) -> None:
    now = _now()
    with connect() as conn:
        conn.execute("""UPDATE surveys SET status = 'fielding', launched_at = COALESCE(launched_at, ?),
                        closes_at = COALESCE(closes_at, ?), updated_at = ? WHERE id = ?""",
                     (now, _plus_minutes(now, deadline_minutes), now, survey_id))


def close_survey(survey_id: str, reason: str) -> bool:
    """Ends fieldwork. Returns False if it was already closed."""
    now = _now()
    with connect() as conn:
        cur = conn.execute("""UPDATE surveys SET status = 'closed', closed_at = ?, close_reason = ?, updated_at = ?
                              WHERE id = ? AND status != 'closed'""", (now, reason, now, survey_id))
        if cur.rowcount:
            conn.execute("""UPDATE invites SET state = 'expired'
                            WHERE survey_id = ? AND state IN ('created', 'invited', 'opened')""", (survey_id,))
    return cur.rowcount == 1


def mark_contacted(token: str, email: str | None, followup: bool) -> None:
    now = _now()
    with connect() as conn:
        if followup:
            conn.execute("UPDATE invites SET last_contacted_at = ?, followups_sent = followups_sent + 1 WHERE token = ?",
                         (now, token))
        else:
            conn.execute("""UPDATE invites SET email = ?, invited_at = ?, last_contacted_at = ?,
                            state = CASE WHEN state = 'created' THEN 'invited' ELSE state END WHERE token = ?""",
                         (email, now, now, token))


def invite_contact_count(token: str) -> int:
    """How many emails this invite has had so far; makes each send's idempotency key unique."""
    with connect() as conn:
        return conn.execute("SELECT COUNT(*) FROM outbox WHERE token = ?", (token,)).fetchone()[0]


def opt_out(token: str) -> bool:
    with connect() as conn:
        cur = conn.execute("""UPDATE invites SET opted_out_at = ?, state = 'opted_out'
                              WHERE token = ? AND opted_out_at IS NULL AND state != 'responded'""", (_now(), token))
    return cur.rowcount == 1


def list_participants(survey_id: str) -> list[dict]:
    with connect() as conn:
        rows = conn.execute("""SELECT i.*, r.submitted_at, r.verified FROM invites i LEFT JOIN responses r USING (token)
                               WHERE i.survey_id = ? ORDER BY i.created_at, i.rowid""", (survey_id,)).fetchall()
    return [{**dict(r), "target": json.loads(r["target"])} for r in rows]


def surveys_in_field() -> list[dict]:
    with connect() as conn:
        rows = conn.execute("SELECT * FROM surveys WHERE status = 'fielding'").fetchall()
    return [_survey_row(r) for r in rows]


def log_event(survey_id: str, type: str, token: str | None = None, detail: dict | None = None) -> None:
    with connect() as conn:
        conn.execute("INSERT INTO events (survey_id, token, type, detail, at) VALUES (?, ?, ?, ?, ?)",
                     (survey_id, token, type, json.dumps(detail) if detail else None, _now()))


def list_events(survey_id: str, limit: int = 200) -> list[dict]:
    with connect() as conn:
        rows = conn.execute("""SELECT e.*, i.target FROM events e LEFT JOIN invites i USING (token)
                               WHERE e.survey_id = ? ORDER BY e.id DESC LIMIT ?""", (survey_id, limit)).fetchall()
    return [{**dict(r), "detail": json.loads(r["detail"]) if r["detail"] else {},
             "target": json.loads(r["target"]) if r["target"] else None} for r in rows]


def add_outbox(survey_id: str, token: str | None, kind: str, to_email: str | None, subject: str, body: str,
               status: str = "logged", provider_id: str | None = None, error: str | None = None) -> None:
    with connect() as conn:
        conn.execute("""INSERT INTO outbox (survey_id, token, kind, to_email, subject, body, status, provider_id, error,
                        created_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                     (survey_id, token, kind, to_email, subject, body, status, provider_id, error, _now()))


def list_outbox(survey_id: str, limit: int = 100) -> list[dict]:
    with connect() as conn:
        rows = conn.execute("SELECT * FROM outbox WHERE survey_id = ? ORDER BY id DESC LIMIT ?",
                            (survey_id, limit)).fetchall()
    return [dict(r) for r in rows]


def save_insights(survey_id: str, stats: dict, report: str, model: str | None) -> None:
    with connect() as conn:
        conn.execute("""INSERT INTO insights (survey_id, stats, report, model, generated_at) VALUES (?, ?, ?, ?, ?)
                        ON CONFLICT (survey_id) DO UPDATE SET stats = excluded.stats, report = excluded.report,
                        model = excluded.model, generated_at = excluded.generated_at""",
                     (survey_id, json.dumps(stats), report, model, _now()))


def get_insights(survey_id: str) -> dict | None:
    with connect() as conn:
        row = conn.execute("SELECT * FROM insights WHERE survey_id = ?", (survey_id,)).fetchone()
    return {**dict(row), "stats": json.loads(row["stats"])} if row else None
