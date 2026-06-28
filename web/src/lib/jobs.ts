import { randomUUID } from "crypto";
import { query } from "./db";
import type { LocalizationJob } from "./types";

const JSON_FIELDS = ["markets", "forks", "agents", "results", "logs"] as const;

type RawRow = Record<string, unknown>;

function parseRow(row: RawRow): LocalizationJob {
  const parsed: RawRow = { ...row };
  for (const field of JSON_FIELDS) {
    const value = parsed[field];
    if (typeof value === "string") {
      try {
        parsed[field] = JSON.parse(value);
      } catch {
        parsed[field] = field === "logs" || field === "markets" ? [] : {};
      }
    }
  }
  for (const ts of ["created_at", "updated_at"] as const) {
    if (parsed[ts] instanceof Date) {
      parsed[ts] = (parsed[ts] as Date).toISOString();
    }
  }
  return parsed as unknown as LocalizationJob;
}

export async function listJobs(limit = 50): Promise<LocalizationJob[]> {
  const { rows } = await query<RawRow>(
    "SELECT * FROM localization_jobs ORDER BY created_at DESC LIMIT $1",
    [limit]
  );
  return rows.map(parseRow);
}

export async function getJob(id: string): Promise<LocalizationJob | null> {
  const { rows } = await query<RawRow>(
    "SELECT * FROM localization_jobs WHERE id = $1",
    [id]
  );
  return rows.length ? parseRow(rows[0]) : null;
}

export interface CreateJobInput {
  campaignId: string;
  videoKey: string;
  audioKey: string;
  sourceBucket: string;
  markets: string[];
}

export async function createJob(input: CreateJobInput): Promise<LocalizationJob> {
  const id = randomUUID();
  const now = new Date().toISOString();
  const initialLog = `[${new Date().toISOString().slice(11, 19)}] Job queued for campaign '${input.campaignId}' with target markets: ${input.markets.join(", ")}`;

  await query(
    `INSERT INTO localization_jobs
       (id, campaign_id, status, markets, video_key, audio_key, source_bucket,
        forks, agents, results, logs, created_at, updated_at)
     VALUES ($1, $2, 'initializing', $3, $4, $5, $6, '{}', '{}', '{}', $7, $8, $9)`,
    [
      id,
      input.campaignId,
      JSON.stringify(input.markets),
      input.videoKey,
      input.audioKey,
      input.sourceBucket,
      JSON.stringify([initialLog]),
      now,
      now,
    ]
  );

  const job = await getJob(id);
  if (!job) throw new Error("Failed to read back created job");
  return job;
}
