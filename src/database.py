import os
import json
import sqlite3
import httpx
from datetime import datetime
from typing import List, Dict, Any, Optional
from src.config import settings
from src.utils.logger import setup_logger

logger = setup_logger("swarm-database")

DB_PATH = os.path.join(
    os.path.dirname(os.path.dirname(__file__)), "jobs.db"
)

def use_insforge() -> bool:
    return bool(settings.INSFORGE_API_KEY)

def get_db_connection() -> sqlite3.Connection:
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn

def execute_raw_sql(query: str, params: list = None) -> dict:
    url = f"{settings.INSFORGE_BASE_URL.rstrip('/')}/api/database/advance/rawsql"
    headers = {
        "Authorization": f"Bearer {settings.INSFORGE_API_KEY}",
        "Content-Type": "application/json"
    }
    payload = {"query": query}
    if params is not None:
        payload["params"] = params
        
    with httpx.Client(timeout=15.0) as client:
        response = client.post(url, headers=headers, json=payload)
        response.raise_for_status()
        return response.json()

def init_db():
    """
    Initializes the database schema.
    For SQLite, creates local tables.
    For InsForge, confirms connection.
    """
    if use_insforge():
        logger.info(f"Initializing InsForge Postgres database connection: {settings.INSFORGE_BASE_URL}")
        try:
            res = execute_raw_sql("SELECT count(*) FROM localization_jobs")
            logger.info(f"InsForge database verified successfully. Current job count: {res['rows'][0]['count']}")
        except Exception as e:
            logger.error(f"Failed to connect to InsForge database: {e}")
            raise e
    else:
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
            conn.execute("CREATE INDEX IF NOT EXISTS idx_jobs_status ON localization_jobs(status)")
            conn.execute("CREATE INDEX IF NOT EXISTS idx_jobs_campaign ON localization_jobs(campaign_id)")
            conn.commit()
        logger.debug("Local SQLite database schema checked and loaded successfully")


def create_job(
    job_id: str,
    campaign_id: str,
    video_key: str,
    audio_key: str,
    source_bucket: str,
    markets: List[str]
) -> None:
    now_str = datetime.utcnow().isoformat()
    if use_insforge():
        query = """
        INSERT INTO localization_jobs 
        (id, campaign_id, status, markets, video_key, audio_key, source_bucket, forks, agents, results, logs, created_at, updated_at)
        VALUES ($1, $2, 'initializing', $3, $4, $5, $6, '{}', '{}', '{}', '[]', $7, $8)
        """
        params = [
            job_id,
            campaign_id,
            json.dumps(markets),
            video_key,
            audio_key,
            source_bucket,
            now_str,
            now_str
        ]
        execute_raw_sql(query, params)
    else:
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
    if use_insforge():
        query = "UPDATE localization_jobs SET status = $1, error = $2, updated_at = $3 WHERE id = $4"
        execute_raw_sql(query, [status, error, now_str, job_id])
    else:
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
    row = get_job(job_id)
    if not row:
        return
    
    forks = row["forks"]
    forks[f"{market}-{asset_type}"] = fork_bucket
    
    if use_insforge():
        query = "UPDATE localization_jobs SET forks = $1, updated_at = $2 WHERE id = $3"
        execute_raw_sql(query, [json.dumps(forks), now_str, job_id])
    else:
        with get_db_connection() as conn:
            conn.execute(
                "UPDATE localization_jobs SET forks = ?, updated_at = ? WHERE id = ?",
                (json.dumps(forks), now_str, job_id)
            )
            conn.commit()
    add_job_log(job_id, f"Bucket fork mapped: market='{market}', type='{asset_type}', bucket='{fork_bucket}'")


def update_job_agent(job_id: str, agent_id: str, agent_status: str, detail: Optional[str] = None) -> None:
    now_str = datetime.utcnow().isoformat()
    row = get_job(job_id)
    if not row:
        return
    
    agents = row["agents"]
    agents[agent_id] = {"status": agent_status, "updated_at": now_str}
    
    if use_insforge():
        query = "UPDATE localization_jobs SET agents = $1, updated_at = $2 WHERE id = $3"
        execute_raw_sql(query, [json.dumps(agents), now_str, job_id])
    else:
        with get_db_connection() as conn:
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
    row = get_job(job_id)
    if not row:
        return
    
    results = row["results"]
    results[market] = result_data
    
    if use_insforge():
        query = "UPDATE localization_jobs SET results = $1, updated_at = $2 WHERE id = $3"
        execute_raw_sql(query, [json.dumps(results), now_str, job_id])
    else:
        with get_db_connection() as conn:
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
    
    row = get_job(job_id)
    if not row:
        return
    
    logs = row["logs"]
    logs.append(formatted_log)
    
    if use_insforge():
        query = "UPDATE localization_jobs SET logs = $1, updated_at = $2 WHERE id = $3"
        execute_raw_sql(query, [json.dumps(logs), now_str, job_id])
    else:
        with get_db_connection() as conn:
            conn.execute(
                "UPDATE localization_jobs SET logs = ?, updated_at = ? WHERE id = ?",
                (json.dumps(logs), now_str, job_id)
            )
            conn.commit()


def get_job(job_id: str) -> Optional[Dict[str, Any]]:
    if use_insforge():
        query = "SELECT * FROM localization_jobs WHERE id = $1"
        res = execute_raw_sql(query, [job_id])
        if not res or not res.get("rows"):
            return None
        row = res["rows"][0]
        parsed_row = dict(row)
        for key in ["markets", "forks", "agents", "results", "logs"]:
            if isinstance(parsed_row.get(key), str):
                try:
                    parsed_row[key] = json.loads(parsed_row[key])
                except Exception:
                    parsed_row[key] = {} if key != "logs" else []
        return parsed_row
    else:
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
    if use_insforge():
        query = "SELECT * FROM localization_jobs ORDER BY created_at DESC LIMIT 50"
        res = execute_raw_sql(query)
        jobs = []
        if res and res.get("rows"):
            for r in res["rows"]:
                parsed_row = dict(r)
                for key in ["markets", "forks", "agents", "results", "logs"]:
                    if isinstance(parsed_row.get(key), str):
                        try:
                            parsed_row[key] = json.loads(parsed_row[key])
                        except Exception:
                            parsed_row[key] = {} if key != "logs" else []
                jobs.append(parsed_row)
        return jobs
    else:
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
