# AGENTS.md

## Stack

OmniSwarm runs on an **AWS + Vercel** stack:

- **Frontend & API:** Next.js 14 (App Router, TypeScript, Tailwind) in `web/`, deployed on **Vercel**.
- **Database:** **Amazon Aurora DSQL** (PostgreSQL-compatible, IAM-authenticated). Node access via `pg` + `@aws-sdk/dsql-signer` (`web/src/lib/db.ts`); Python access via `psycopg` + boto3 tokens (`src/database.py`). Schema in `web/db/schema.sql`.
- **Object storage:** **Amazon S3** (master + localized-output buckets), browser access via presigned URLs (`web/src/lib/s3.ts`, `src/storage.py`).
- **Worker:** Python FastAPI pipeline (FFmpeg + Demucs + Gemini) in `src/`, triggered via `POST /worker/run`.

## Conventions

- Credentials are read from `APP_AWS_*` env vars (not `AWS_*`, which Vercel/Lambda reserves). Never hardcode or commit keys.
- The single source of truth for job state is the `localization_jobs` table in Aurora DSQL; both the Vercel app and the worker read/write it.
- Nested fields (`markets`, `forks`, `agents`, `results`, `logs`) are stored as JSON text for parity between the Node and Python layers.
