import { NextRequest, NextResponse } from "next/server";
import { presignPut, MASTER_BUCKET } from "@/lib/s3";

export const runtime = "nodejs";
export const dynamic = "force-dynamic";

/**
 * Returns presigned PUT URLs so the brand team can upload the master video and
 * voiceover straight to the S3 master bucket from the browser.
 */
export async function POST(req: NextRequest) {
  try {
    const body = await req.json().catch(() => ({}));
    const campaignId = String(body.campaignId ?? "").trim();
    if (!campaignId) {
      return NextResponse.json({ error: "campaignId is required" }, { status: 400 });
    }

    const videoKey = `campaigns/${campaignId}/master.mp4`;
    const audioKey = `campaigns/${campaignId}/voiceover.wav`;

    const [videoUrl, audioUrl] = await Promise.all([
      presignPut(MASTER_BUCKET, videoKey, "video/mp4"),
      presignPut(MASTER_BUCKET, audioKey, "audio/wav"),
    ]);

    return NextResponse.json({
      bucket: MASTER_BUCKET,
      video: { key: videoKey, url: videoUrl },
      audio: { key: audioKey, url: audioUrl },
    });
  } catch (err) {
    return NextResponse.json(
      { error: err instanceof Error ? err.message : String(err) },
      { status: 500 }
    );
  }
}
