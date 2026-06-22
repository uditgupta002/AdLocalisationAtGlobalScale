import sqlite3
import os
import json
from datetime import datetime
from typing import List, Dict, Any, Optional
from src.utils.logger import setup_logger

logger = setup_logger("swarm-database")

DB_PATH = os.path.join(
    os.path.dirname(os.path.dirname(__file__)), "jobs.db"
)

def get_db_connection() -> sqlite3.Connection:
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn

def init_db():
    """
    Initializes the local SQLite database schema.
    """
    logger.info(f"Initializing SQLite database at: {DB_PATH}")
    with get_db_connection() as conn:
        conn.execute("""
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
        """)
        # Indexes for speed
        conn.execute("CREATE INDEX IF NOT EXISTS idx_jobs_status ON localization_jobs(status)")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_jobs_campaign ON localization_jobs(campaign_id)")
        conn.commit()
    logger.debug("Database schema checked and loaded successfully")


def create_job(
    job_id: str,
    campaign_id: str,
    video_key: str,
    audio_key: str,
    source_bucket: str,
    markets: List[str]
) -> None:
    now_str = datetime.utcnow().isoformat()
    with get_db_connection() as conn:
        conn.execute(
            """
            INSERT INTO localization_jobs 
            (id, campaign_id, status, markets, video_key, audio_key, source_bucket, forks, agents, results, logs, created_at, updated_at)
            VALUES (?, ?, 'initializing', ?, ?, ?, ?, '{}', '{}', '{}', '[]', ?, ?)
            """,
            (
                job_id,
                campaign_id,
                json.dumps(markets),
                video_key,
                audio_key,
                source_bucket,
                now_str,
                now_str
            )
        )
        conn.commit()
    add_job_log(job_id, f"Job initialized for campaign '{campaign_id}' with target markets: {markets}")


def update_job_status(job_id: str, status: str, error: Optional[str] = None) -> None:
    now_str = datetime.utcnow().isoformat()
    with get_db_connection() as conn:
        conn.execute(
            "UPDATE localization_jobs SET status = ?, error = ?, updated_at = ? WHERE id = ?",
            (status, error, now_str, job_id)
        )
        conn.commit()
    
    log_msg = f"Status transition: {status}"
    if error:
        log_msg += f" (Error: {error})"
    add_job_log(job_id, log_msg)


def update_job_fork(job_id: str, market: str, asset_type: str, fork_bucket: str) -> None:
    now_str = datetime.utcnow().isoformat()
    with get_db_connection() as conn:
        row = conn.execute("SELECT forks FROM localization_jobs WHERE id = ?", (job_id,)).fetchone()
        if not row:
            return
        
        forks = json.loads(row["forks"])
        forks[f"{market}-{asset_type}"] = fork_bucket
        
        conn.execute(
            "UPDATE localization_jobs SET forks = ?, updated_at = ? WHERE id = ?",
            (json.dumps(forks), now_str, job_id)
        )
        conn.commit()
    add_job_log(job_id, f"Bucket fork mapped: market='{market}', type='{asset_type}', bucket='{fork_bucket}'")


def update_job_agent(job_id: str, agent_id: str, agent_status: str, detail: Optional[str] = None) -> None:
    now_str = datetime.utcnow().isoformat()
    with get_db_connection() as conn:
        row = conn.execute("SELECT agents FROM localization_jobs WHERE id = ?", (job_id,)).fetchone()
        if not row:
            return
        
        agents = json.loads(row["agents"])
        agents[agent_id] = {"status": agent_status, "updated_at": now_str}
        
        conn.execute(
            "UPDATE localization_jobs SET agents = ?, updated_at = ? WHERE id = ?",
            (json.dumps(agents), now_str, job_id)
        )
        conn.commit()
    
    log_msg = f"Agent '{agent_id}' updated to status: '{agent_status}'"
    if detail:
        log_msg += f" - {detail}"
    add_job_log(job_id, log_msg)


def update_job_result(job_id: str, market: str, result_data: Dict[str, Any]) -> None:
    now_str = datetime.utcnow().isoformat()
    with get_db_connection() as conn:
        row = conn.execute("SELECT results FROM localization_jobs WHERE id = ?", (job_id,)).fetchone()
        if not row:
            return
        
        results = json.loads(row["results"])
        results[market] = result_data
        
        conn.execute(
            "UPDATE localization_jobs SET results = ?, updated_at = ? WHERE id = ?",
            (json.dumps(results), now_str, job_id)
        )
        conn.commit()
    add_job_log(job_id, f"Asset assembly completed for market '{market}'")


def add_job_log(job_id: str, message: str) -> None:
    """
    Appends a log message to the job's real-time audit log list.
    """
    now_str = datetime.utcnow().isoformat()
    formatted_log = f"[{datetime.utcnow().strftime('%H:%M:%S')}] {message}"
    logger.info(f"JOB [{job_id[:8]}]: {message}")
    
    with get_db_connection() as conn:
        row = conn.execute("SELECT logs FROM localization_jobs WHERE id = ?", (job_id,)).fetchone()
        if not row:
            return
        
        logs = json.loads(row["logs"])
        logs.append(formatted_log)
        
        conn.execute(
            "UPDATE localization_jobs SET logs = ?, updated_at = ? WHERE id = ?",
            (json.dumps(logs), now_str, job_id)
        )
        conn.commit()


def get_job(job_id: str) -> Optional[Dict[str, Any]]:
    with get_db_connection() as conn:
        row = conn.execute("SELECT * FROM localization_jobs WHERE id = ?", (job_id,)).fetchone()
        if not row:
            return None
        
        res = dict(row)
        res["markets"] = json.loads(res["markets"])
        res["forks"] = json.loads(res["forks"])
        res["agents"] = json.loads(res["agents"])
        res["results"] = json.loads(res["results"])
        res["logs"] = json.loads(res["logs"])
        return res


def list_jobs() -> List[Dict[str, Any]]:
    with get_db_connection() as conn:
        rows = conn.execute("SELECT * FROM localization_jobs ORDER BY created_at DESC LIMIT 50").fetchall()
        jobs = []
        for r in rows:
            res = dict(r)
            res["markets"] = json.loads(res["markets"])
            res["forks"] = json.loads(res["forks"])
            res["agents"] = json.loads(res["agents"])
            res["results"] = json.loads(res["results"])
            res["logs"] = json.loads(res["logs"])
            jobs.append(res)
        return jobs

# Run schema setup automatically on module load
init_db()
