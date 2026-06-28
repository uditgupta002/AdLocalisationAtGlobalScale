import { NextRequest, NextResponse } from "next/server";
import { createJob, listJobs } from "@/lib/jobs";
import { MASTER_BUCKET } from "@/lib/s3";
import { ALL_MARKETS, getMarket } from "@/lib/markets";

export const runtime = "nodejs";
export const dynamic = "force-dynamic";

export async function GET() {
  try {
    const jobs = await listJobs();
    return NextResponse.json({ jobs });
  } catch (err) {
    return NextResponse.json(
      { error: err instanceof Error ? err.message : String(err) },
      { status: 500 }
    );
  }
}

export async function POST(req: NextRequest) {
  try {
    const body = await req.json().catch(() => ({}));
    const campaignId = String(body.campaignId ?? "").trim();
    if (!campaignId) {
      return NextResponse.json({ error: "campaignId is required" }, { status: 400 });
    }

    const requested: string[] = Array.isArray(body.markets) && body.markets.length
      ? body.markets
      : ALL_MARKETS;
    const markets = requested.filter((m) => getMarket(m));
    if (!markets.length) {
      return NextResponse.json({ error: "no valid markets selected" }, { status: 400 });
    }

    const videoKey = body.videoKey ?? `campaigns/${campaignId}/master.mp4`;
    const audioKey = body.audioKey ?? `campaigns/${campaignId}/voiceover.wav`;

    const job = await createJob({
      campaignId,
      videoKey,
      audioKey,
      sourceBucket: MASTER_BUCKET,
      markets,
    });

    return NextResponse.json({ job }, { status: 201 });
  } catch (err) {
    return NextResponse.json(
      { error: err instanceof Error ? err.message : String(err) },
      { status: 500 }
    );
  }
}
