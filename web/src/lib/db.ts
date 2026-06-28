import { Pool } from "pg";
import { DsqlSigner } from "@aws-sdk/dsql-signer";
import { getRegion, getCredentials } from "./aws";

/**
 * Aurora DSQL connection pool.
 *
 * DSQL speaks the standard PostgreSQL wire protocol but requires short-lived
 * IAM auth tokens in place of a static password. We generate a fresh admin
 * token per new connection via DsqlSigner; node-postgres accepts an async
 * `password` function for exactly this case.
 */
let pool: Pool | null = null;

function getEndpoint(): string {
  const host = process.env.DSQL_ENDPOINT;
  if (!host) {
    throw new Error("Missing DSQL_ENDPOINT (your Aurora DSQL cluster endpoint)");
  }
  return host;
}

export function getPool(): Pool {
  if (pool) return pool;

  const host = getEndpoint();
  const region = getRegion();

  pool = new Pool({
    host,
    port: 5432,
    database: "postgres",
    user: "admin",
    ssl: { rejectUnauthorized: true },
    // Keep the pool small; serverless functions are short-lived.
    max: 1,
    idleTimeoutMillis: 10_000,
    connectionTimeoutMillis: 15_000,
    password: async () => {
      const signer = new DsqlSigner({
        hostname: host,
        region,
        credentials: getCredentials(),
      });
      return signer.getDbConnectAdminAuthToken();
    },
  });

  pool.on("error", (err) => {
    console.error("[dsql] idle client error", err);
  });

  return pool;
}

export async function query<T = Record<string, unknown>>(
  text: string,
  params?: unknown[]
): Promise<{ rows: T[] }> {
  const p = getPool();
  const res = await p.query(text, params as never[]);
  return { rows: res.rows as T[] };
}
