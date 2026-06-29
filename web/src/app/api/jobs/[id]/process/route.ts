import { NextRequest, NextResponse } from "next/server";
import { processJob } from "@/lib/process";
import { triggerWorker } from "@/lib/worker";

export const runtime = "nodejs";
export const dynamic = "force-dynamic";
export const maxDuration = 60;

export async function POST(
  _req: NextRequest,
  { params }: { params: { id: string } }
) {
  try {
    // When a real Python worker is configured (FFmpeg + Demucs + Gemini),
    // hand off the job for genuine per-market translation/dubbing. Otherwise
    // fall back to the self-contained serverless pipeline.
    if (process.env.WORKER_URL) {
      const r = await triggerWorker(params.id);
      if (!r.ok) {
        return NextResponse.json(
          { ok: false, error: r.detail ?? "worker trigger failed" },
          { status: 502 }
        );
      }
      return NextResponse.json({ ok: true, mode: "worker" });
    }

    await processJob(params.id);
    return NextResponse.json({ ok: true, mode: "serverless" });
  } catch (err) {
    return NextResponse.json(
      { ok: false, error: err instanceof Error ? err.message : String(err) },
      { status: 500 }
    );
  }
}
