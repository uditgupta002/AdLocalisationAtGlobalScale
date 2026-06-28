import { NextRequest, NextResponse } from "next/server";
import { getJob } from "@/lib/jobs";
import { presignGet } from "@/lib/s3";

export const runtime = "nodejs";
export const dynamic = "force-dynamic";

export async function GET(
  _req: NextRequest,
  { params }: { params: { id: string } }
) {
  try {
    const job = await getJob(params.id);
    if (!job) {
      return NextResponse.json({ error: "job not found" }, { status: 404 });
    }

    // Attach presigned URLs for any completed market outputs so the UI can
    // play original vs. localized media directly from private S3.
    const previews: Record<string, { video?: string; audio?: string }> = {};
    for (const [market, result] of Object.entries(job.results ?? {})) {
      try {
        previews[market] = {
          video: await presignGet(result.output_bucket, result.merged_ad_key),
          audio: await presignGet(result.output_bucket, result.localized_audio_key),
        };
      } catch {
        previews[market] = {};
      }
    }

    return NextResponse.json({ job, previews });
  } catch (err) {
    return NextResponse.json(
      { error: err instanceof Error ? err.message : String(err) },
      { status: 500 }
    );
  }
}
