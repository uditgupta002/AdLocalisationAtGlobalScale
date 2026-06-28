/**
 * Trigger the Python media-processing worker (the existing OmniSwarm pipeline:
 * FFmpeg + Demucs + Gemini). The worker reads/writes the same Aurora DSQL row
 * and S3 buckets, so Vercel only needs to hand it a job id.
 */
export async function triggerWorker(jobId: string): Promise<{ ok: boolean; detail?: string }> {
  const base = process.env.WORKER_URL;
  if (!base) {
    return { ok: false, detail: "WORKER_URL not configured" };
  }
  try {
    const res = await fetch(`${base.replace(/\/$/, "")}/worker/run`, {
      method: "POST",
      headers: {
        "Content-Type": "application/json",
        Authorization: `Bearer ${process.env.WORKER_AUTH_TOKEN ?? ""}`,
      },
      body: JSON.stringify({ job_id: jobId }),
    });
    if (!res.ok) {
      return { ok: false, detail: `Worker responded ${res.status}` };
    }
    return { ok: true };
  } catch (err) {
    return { ok: false, detail: err instanceof Error ? err.message : String(err) };
  }
}
