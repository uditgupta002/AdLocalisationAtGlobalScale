import os
import json
import sqlite3
from datetime import datetime
from typing import List, Dict, Any, Optional
from src.config import settings
from src.utils.logger import setup_logger

logger = setup_logger("swarm-database")

DB_PATH = os.path.join(
    os.path.dirname(os.path.dirname(__file__)), "jobs.db"
)


def use_dsql() -> bool:
    """Aurora DSQL is active whenever a cluster endpoint is configured."""
    return bool(settings.DSQL_ENDPOINT)


# ---------------------------------------------------------------------------
# Aurora DSQL (PostgreSQL wire protocol + short-lived IAM auth tokens)
# ---------------------------------------------------------------------------
def _dsql_connect():
    """
    Open a fresh Aurora DSQL connection. DSQL requires an IAM auth token in
    place of a static password; we mint an admin token per connection via
    boto3 and pass it to psycopg.
    """
    import boto3
    import psycopg

    region = settings.APP_AWS_REGION
    host = settings.DSQL_ENDPOINT

    session_kwargs: Dict[str, Any] = {"region_name": region}
    if settings.APP_AWS_ACCESS_KEY_ID and settings.APP_AWS_SECRET_ACCESS_KEY:
        session_kwargs["aws_access_key_id"] = settings.APP_AWS_ACCESS_KEY_ID
        session_kwargs["aws_secret_access_key"] = settings.APP_AWS_SECRET_ACCESS_KEY

    client = boto3.client("dsql", **session_kwargs)
    token = client.generate_db_connect_admin_auth_token(host, region)

    return psycopg.connect(
        host=host,
        port=5432,
        dbname="postgres",
        user="admin",
        password=token,
        sslmode="require",
        autocommit=True,
    )


def _pg_execute(query: str, params: Optional[list] = None, fetch: bool = False):
    conn = _dsql_connect()
    try:
        with conn.cursor() as cur:
            cur.execute(query, params or [])
            if fetch:
                cols = [d[0] for d in cur.description]
                return [dict(zip(cols, row)) for row in cur.fetchall()]
            return None
    finally:
        conn.close()


def get_db_connection() -> sqlite3.Connection:
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def init_db():
    """Initialize the schema for whichever backend is active."""
    if use_dsql():
        logger.info(f"Initializing Aurora DSQL database: {settings.DSQL_ENDPOINT}")
        try:
            _pg_execute(
                """
                CREATE TABLE IF NOT EXISTS localization_jobs (
                    id            text PRIMARY KEY,
                    campaign_id   text        NOT NULL,
                    status        text        NOT NULL DEFAULT 'initializing',
                    markets       text        NOT NULL DEFAULT '[]',
                    video_key     text        NOT NULL,
                    audio_key     text        NOT NULL,
                    source_bucket text        NOT NULL,
                    forks         text        NOT NULL DEFAULT '{}',
                    agents        text        NOT NULL DEFAULT '{}',
                    results       text        NOT NULL DEFAULT '{}',
                    logs          text        NOT NULL DEFAULT '[]',
                    error         text,
                    created_at    timestamptz NOT NULL DEFAULT now(),
                    updated_at    timestamptz NOT NULL DEFAULT now()
                )
                """
            )
            count = _pg_execute("SELECT count(*) AS c FROM localization_jobs", fetch=True)
            logger.info(f"Aurora DSQL verified. Current job count: {count[0]['c']}")
        except Exception as e:
            logger.error(f"Failed to connect to Aurora DSQL: {e}")
            raise
    else:
        logger.info(f"Initializing SQLite database at: {DB_PATH}")
        with get_db_connection() as conn:
            conn.execute(
                """
            CREATE TABLE IF NOT EXISTS localization_jobs (
                id TEXT PRIMARY KEY,
                campaign_id TEXT NOT NULL,
                status TEXT NOT NULL DEFAULT 'initializing',
                markets TEXT NOT NULL DEFAULT '[]',
                video_key TEXT NOT NULL,
                audio_key TEXT NOT NULL,
                source_bucket TEXT NOT NULL,
                forks TEXT NOT NULL DEFAULT '{}',
                agents TEXT NOT NULL DEFAULT '{}',
                results TEXT NOT NULL DEFAULT '{}',
                logs TEXT NOT NULL DEFAULT '[]',
                error TEXT,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL
            )
            """
            )
            conn.execute("CREATE INDEX IF NOT EXISTS idx_jobs_status ON localization_jobs(status)")
            conn.execute("CREATE INDEX IF NOT EXISTS idx_jobs_campaign ON localization_jobs(campaign_id)")
            conn.commit()
        logger.debug("Local SQLite schema ready")


def create_job(
    job_id: str,
    campaign_id: str,
    video_key: str,
    audio_key: str,
    source_bucket: str,
    markets: List[str],
) -> None:
    now_str = datetime.utcnow().isoformat()
    if use_dsql():
        _pg_execute(
            """
            INSERT INTO localization_jobs
            (id, campaign_id, status, markets, video_key, audio_key, source_bucket, forks, agents, results, logs, created_at, updated_at)
            VALUES (%s, %s, 'initializing', %s, %s, %s, %s, '{}', '{}', '{}', '[]', %s, %s)
            """,
            [job_id, campaign_id, json.dumps(markets), video_key, audio_key, source_bucket, now_str, now_str],
        )
    else:
        with get_db_connection() as conn:
            conn.execute(
                """
                INSERT INTO localization_jobs
                (id, campaign_id, status, markets, video_key, audio_key, source_bucket, forks, agents, results, logs, created_at, updated_at)
                VALUES (?, ?, 'initializing', ?, ?, ?, ?, '{}', '{}', '{}', '[]', ?, ?)
                """,
                (job_id, campaign_id, json.dumps(markets), video_key, audio_key, source_bucket, now_str, now_str),
            )
            conn.commit()
    add_job_log(job_id, f"Job initialized for campaign '{campaign_id}' with target markets: {markets}")


def update_job_status(job_id: str, status: str, error: Optional[str] = None) -> None:
    now_str = datetime.utcnow().isoformat()
    if use_dsql():
        _pg_execute(
            "UPDATE localization_jobs SET status = %s, error = %s, updated_at = %s WHERE id = %s",
            [status, error, now_str, job_id],
        )
    else:
        with get_db_connection() as conn:
            conn.execute(
                "UPDATE localization_jobs SET status = ?, error = ?, updated_at = ? WHERE id = ?",
                (status, error, now_str, job_id),
            )
            conn.commit()

    log_msg = f"Status transition: {status}"
    if error:
        log_msg += f" (Error: {error})"
    add_job_log(job_id, log_msg)


def _update_json_field(job_id: str, field: str, value: Any) -> None:
    now_str = datetime.utcnow().isoformat()
    serialized = json.dumps(value)
    if use_dsql():
        _pg_execute(
            f"UPDATE localization_jobs SET {field} = %s, updated_at = %s WHERE id = %s",
            [serialized, now_str, job_id],
        )
    else:
        with get_db_connection() as conn:
            conn.execute(
                f"UPDATE localization_jobs SET {field} = ?, updated_at = ? WHERE id = ?",
                (serialized, now_str, job_id),
            )
            conn.commit()


def update_job_fork(job_id: str, market: str, asset_type: str, fork_bucket: str) -> None:
    row = get_job(job_id)
    if not row:
        return
    forks = row["forks"]
    forks[f"{market}-{asset_type}"] = fork_bucket
    _update_json_field(job_id, "forks", forks)
    add_job_log(job_id, f"Bucket fork mapped: market='{market}', type='{asset_type}', bucket='{fork_bucket}'")


def update_job_agent(job_id: str, agent_id: str, agent_status: str, detail: Optional[str] = None) -> None:
    row = get_job(job_id)
    if not row:
        return
    agents = row["agents"]
    agents[agent_id] = {"status": agent_status, "updated_at": datetime.utcnow().isoformat()}
    _update_json_field(job_id, "agents", agents)

    log_msg = f"Agent '{agent_id}' updated to status: '{agent_status}'"
    if detail:
        log_msg += f" - {detail}"
    add_job_log(job_id, log_msg)


def update_job_result(job_id: str, market: str, result_data: Dict[str, Any]) -> None:
    row = get_job(job_id)
    if not row:
        return
    results = row["results"]
    results[market] = result_data
    _update_json_field(job_id, "results", results)
    add_job_log(job_id, f"Asset assembly completed for market '{market}'")


def add_job_log(job_id: str, message: str) -> None:
    formatted_log = f"[{datetime.utcnow().strftime('%H:%M:%S')}] {message}"
    logger.info(f"JOB [{job_id[:8]}]: {message}")

    row = get_job(job_id)
    if not row:
        return
    logs = row["logs"]
    logs.append(formatted_log)
    _update_json_field(job_id, "logs", logs)


def _parse_json_fields(row: Dict[str, Any]) -> Dict[str, Any]:
    for key in ["markets", "forks", "agents", "results", "logs"]:
        value = row.get(key)
        if isinstance(value, str):
            try:
                row[key] = json.loads(value)
            except Exception:
                row[key] = [] if key in ("logs", "markets") else {}
    for ts in ["created_at", "updated_at"]:
        if isinstance(row.get(ts), datetime):
            row[ts] = row[ts].isoformat()
    return row


def get_job(job_id: str) -> Optional[Dict[str, Any]]:
    if use_dsql():
        rows = _pg_execute("SELECT * FROM localization_jobs WHERE id = %s", [job_id], fetch=True)
        if not rows:
            return None
        return _parse_json_fields(dict(rows[0]))
    else:
        with get_db_connection() as conn:
            row = conn.execute("SELECT * FROM localization_jobs WHERE id = ?", (job_id,)).fetchone()
            if not row:
                return None
            return _parse_json_fields(dict(row))


def list_jobs() -> List[Dict[str, Any]]:
    if use_dsql():
        rows = _pg_execute(
            "SELECT * FROM localization_jobs ORDER BY created_at DESC LIMIT 50", fetch=True
        )
        return [_parse_json_fields(dict(r)) for r in (rows or [])]
    else:
        with get_db_connection() as conn:
            rows = conn.execute(
                "SELECT * FROM localization_jobs ORDER BY created_at DESC LIMIT 50"
            ).fetchall()
            return [_parse_json_fields(dict(r)) for r in rows]


# Run schema setup automatically on module load
init_db()
