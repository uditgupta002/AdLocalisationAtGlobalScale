"use client";

import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import type { LocalizationJob } from "@/lib/types";
import { MARKET_CONFIGS, ALL_MARKETS } from "@/lib/markets";

type Preview = { video?: string; audio?: string };

const STATUS_META: Record<string, { label: string; color: string; dot: string }> = {
  initializing: { label: "Queued", color: "text-slate-300", dot: "bg-slate-400" },
  "security-scanning": { label: "Security scan", color: "text-amber-300", dot: "bg-amber-400" },
  forking: { label: "Forking buckets", color: "text-sky-300", dot: "bg-sky-400" },
  processing: { label: "Processing", color: "text-indigo-300", dot: "bg-indigo-400 animate-pulse" },
  assembling: { label: "Assembling", color: "text-violet-300", dot: "bg-violet-400 animate-pulse" },
  completed: { label: "Completed", color: "text-emerald-300", dot: "bg-emerald-400" },
  failed: { label: "Failed", color: "text-rose-300", dot: "bg-rose-400" },
};

function StatusBadge({ status }: { status: string }) {
  const meta = STATUS_META[status] ?? STATUS_META.initializing;
  return (
    <span className="inline-flex items-center gap-2 text-xs font-medium">
      <span className={`h-2 w-2 rounded-full ${meta.dot}`} />
      <span className={meta.color}>{meta.label}</span>
    </span>
  );
}

function timeAgo(iso: string): string {
  const diff = Date.now() - new Date(iso).getTime();
  const s = Math.floor(diff / 1000);
  if (s < 60) return `${s}s ago`;
  const m = Math.floor(s / 60);
  if (m < 60) return `${m}m ago`;
  const h = Math.floor(m / 60);
  if (h < 24) return `${h}h ago`;
  return `${Math.floor(h / 24)}d ago`;
}

export default function Dashboard() {
  const [jobs, setJobs] = useState<LocalizationJob[]>([]);
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const [detail, setDetail] = useState<{ job: LocalizationJob; previews: Record<string, Preview> } | null>(null);
  const [campaignId, setCampaignId] = useState("");
  const [markets, setMarkets] = useState<string[]>(ALL_MARKETS);
  const [videoFile, setVideoFile] = useState<File | null>(null);
  const [audioFile, setAudioFile] = useState<File | null>(null);
  const [submitting, setSubmitting] = useState(false);
  const [phase, setPhase] = useState<string>("");
  const [error, setError] = useState<string | null>(null);
  const [health, setHealth] = useState<"unknown" | "healthy" | "degraded">("unknown");
  const logRef = useRef<HTMLDivElement>(null);

  const fetchJobs = useCallback(async () => {
    try {
      const res = await fetch("/api/jobs", { cache: "no-store" });
      const data = await res.json();
      if (res.ok) {
        setJobs(data.jobs ?? []);
        setError(null);
      } else {
        setError(data.error ?? "Failed to load jobs");
      }
    } catch (e) {
      setError(e instanceof Error ? e.message : "Network error");
    }
  }, []);

  const fetchDetail = useCallback(async (id: string) => {
    try {
      const res = await fetch(`/api/jobs/${id}`, { cache: "no-store" });
      const data = await res.json();
      if (res.ok) setDetail(data);
    } catch {
      /* ignore transient */
    }
  }, []);

  useEffect(() => {
    fetchJobs();
    fetch("/api/health")
      .then((r) => r.json())
      .then((d) => setHealth(d.status === "healthy" ? "healthy" : "degraded"))
      .catch(() => setHealth("degraded"));
    const t = setInterval(fetchJobs, 2500);
    return () => clearInterval(t);
  }, [fetchJobs]);

  useEffect(() => {
    if (!selectedId) return;
    fetchDetail(selectedId);
    const t = setInterval(() => fetchDetail(selectedId), 2000);
    return () => clearInterval(t);
  }, [selectedId, fetchDetail]);

  useEffect(() => {
    if (logRef.current) logRef.current.scrollTop = logRef.current.scrollHeight;
  }, [detail?.job.logs.length]);

  const toggleMarket = (m: string) =>
    setMarkets((prev) => (prev.includes(m) ? prev.filter((x) => x !== m) : [...prev, m]));

  const launchJob = async (
    cid: string,
    mkts: string[],
    vFile: File | null,
    aFile: File | null
  ) => {
    if (!cid || !mkts.length) return;
    setSubmitting(true);
    setError(null);
    try {
      // 1. Optionally upload master assets straight to S3 via presigned PUT.
      if (vFile || aFile) {
        setPhase("Uploading master assets to S3…");
        const presRes = await fetch("/api/upload", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ campaignId: cid }),
        });
        const pres = await presRes.json();
        if (!presRes.ok) throw new Error(pres.error ?? "Upload presign failed");
        const puts: Promise<Response>[] = [];
        if (vFile)
          puts.push(fetch(pres.video.url, { method: "PUT", headers: { "Content-Type": "video/mp4" }, body: vFile }));
        if (aFile)
          puts.push(fetch(pres.audio.url, { method: "PUT", headers: { "Content-Type": "audio/wav" }, body: aFile }));
        await Promise.all(puts);
      }

      // 2. Create the job row in Aurora DSQL.
      setPhase("Creating job in Aurora DSQL…");
      const res = await fetch("/api/jobs", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ campaignId: cid, markets: mkts }),
      });
      const data = await res.json();
      if (!res.ok) throw new Error(data.error ?? "Failed to launch job");

      setSelectedId(data.job.id);
      setCampaignId("");
      setVideoFile(null);
      setAudioFile(null);
      await fetchJobs();

      // 3. Kick off the serverless localization pipeline (fire-and-forget;
      // the dashboard polls Aurora DSQL for live progress).
      setPhase("Launching agent swarm…");
      fetch(`/api/jobs/${data.job.id}/process`, { method: "POST" }).catch(() => {});
    } catch (e) {
      setError(e instanceof Error ? e.message : "Network error");
    } finally {
      setSubmitting(false);
      setPhase("");
    }
  };

  const submit = () => launchJob(campaignId.trim(), markets, videoFile, audioFile);

  // One-click demo: uses the bundled sample creative + all markets so judges
  // can see the full pipeline run without any setup.
  const runDemo = () => {
    const cid = `demo_${Date.now().toString(36)}`;
    launchJob(cid, ALL_MARKETS, null, null);
  };

  const selected = detail?.job ?? jobs.find((j) => j.id === selectedId) ?? null;
  const previews = detail?.previews ?? {};

  const stats = useMemo(() => {
    const total = jobs.length;
    const active = jobs.filter((j) => !["completed", "failed"].includes(j.status)).length;
    const done = jobs.filter((j) => j.status === "completed").length;
    return { total, active, done };
  }, [jobs]);

  return (
    <div className="mx-auto max-w-7xl px-5 py-8">
      <header className="mb-8 flex flex-wrap items-center justify-between gap-4">
        <div>
          <div className="flex items-center gap-3">
            <span className="text-3xl">🐝</span>
            <h1 className="text-2xl font-semibold tracking-tight">OmniSwarm</h1>
            <span className="rounded-full border border-[var(--border)] bg-[var(--surface)] px-2.5 py-0.5 text-[11px] text-[var(--muted)]">
              Global Ad Localization
            </span>
          </div>
          <p className="mt-1 text-sm text-[var(--muted)]">
            Autonomous multi-agent localization pipeline · powered by{" "}
            <span className="text-[var(--foreground)]">Aurora DSQL</span> +{" "}
            <span className="text-[var(--foreground)]">AWS S3</span>, shipped on Vercel
          </p>
        </div>
        <div className="flex items-center gap-2 text-xs">
          <span className="rounded-md border border-[var(--border)] bg-[var(--surface)] px-2.5 py-1.5">
            Aurora DSQL
          </span>
          <span className="rounded-md border border-[var(--border)] bg-[var(--surface)] px-2.5 py-1.5">
            Amazon S3
          </span>
          <span
            className={`inline-flex items-center gap-1.5 rounded-md border border-[var(--border)] bg-[var(--surface)] px-2.5 py-1.5 ${
              health === "healthy" ? "text-emerald-300" : health === "degraded" ? "text-rose-300" : "text-[var(--muted)]"
            }`}
          >
            <span
              className={`h-2 w-2 rounded-full ${
                health === "healthy" ? "bg-emerald-400" : health === "degraded" ? "bg-rose-400" : "bg-slate-500"
              }`}
            />
            DB {health}
          </span>
        </div>
      </header>

      <div className="grid grid-cols-1 gap-6 lg:grid-cols-12">
        {/* Left column */}
        <div className="space-y-6 lg:col-span-5">
          {/* One-click demo banner */}
          <section className="rounded-2xl border border-[var(--accent)]/40 bg-gradient-to-br from-[var(--accent)]/15 to-[var(--accent-2)]/10 p-5">
            <div className="flex items-center gap-2">
              <span className="text-lg">⚡</span>
              <h2 className="text-sm font-semibold">Judges — try it instantly</h2>
            </div>
            <p className="mb-4 mt-1 text-xs text-[var(--muted)]">
              Runs the full pipeline on our sample ad across all 4 markets. No setup —
              localized in seconds on Aurora DSQL + S3.
            </p>
            <button
              onClick={runDemo}
              disabled={submitting}
              className="w-full rounded-lg bg-[var(--accent)] px-4 py-2.5 text-sm font-semibold text-black transition hover:brightness-110 disabled:cursor-not-allowed disabled:opacity-40"
            >
              {submitting ? phase || "Running…" : "▶  Run Instant Demo"}
            </button>
          </section>

          {/* Trigger panel */}
          <section className="rounded-2xl border border-[var(--border)] bg-[var(--surface)] p-5">
            <h2 className="mb-1 text-sm font-semibold">Or launch your own campaign</h2>
            <p className="mb-4 text-xs text-[var(--muted)]">Upload your own video/audio, or leave blank to use the sample.</p>
            <label className="mb-1.5 block text-xs text-[var(--muted)]">Campaign ID</label>
            <input
              value={campaignId}
              onChange={(e) => setCampaignId(e.target.value)}
              placeholder="e.g. burger_campaign"
              className="mb-4 w-full rounded-lg border border-[var(--border)] bg-[var(--surface-2)] px-3 py-2 text-sm outline-none focus:border-[var(--accent-2)]"
            />
            <label className="mb-2 block text-xs text-[var(--muted)]">
              Master creative <span className="opacity-60">(optional — uses a sample if empty)</span>
            </label>
            <div className="mb-4 grid grid-cols-2 gap-2">
              <label className="flex cursor-pointer flex-col gap-1 rounded-lg border border-[var(--border)] bg-[var(--surface-2)] px-3 py-2 text-xs hover:border-[var(--muted)]">
                <span className="text-[var(--muted)]">🎬 Video {videoFile ? "✓" : ""}</span>
                <span className="truncate">{videoFile?.name ?? "Choose .mp4"}</span>
                <input
                  type="file"
                  accept="video/mp4,video/*"
                  className="hidden"
                  onChange={(e) => setVideoFile(e.target.files?.[0] ?? null)}
                />
              </label>
              <label className="flex cursor-pointer flex-col gap-1 rounded-lg border border-[var(--border)] bg-[var(--surface-2)] px-3 py-2 text-xs hover:border-[var(--muted)]">
                <span className="text-[var(--muted)]">🎙️ Audio {audioFile ? "✓" : ""}</span>
                <span className="truncate">{audioFile?.name ?? "Choose .wav"}</span>
                <input
                  type="file"
                  accept="audio/wav,audio/*"
                  className="hidden"
                  onChange={(e) => setAudioFile(e.target.files?.[0] ?? null)}
                />
              </label>
            </div>
            <label className="mb-2 block text-xs text-[var(--muted)]">Target markets</label>
            <div className="mb-5 grid grid-cols-2 gap-2">
              {ALL_MARKETS.map((m) => {
                const cfg = MARKET_CONFIGS[m];
                const on = markets.includes(m);
                return (
                  <button
                    key={m}
                    onClick={() => toggleMarket(m)}
                    className={`flex items-center gap-2 rounded-lg border px-3 py-2 text-left text-sm transition ${
                      on
                        ? "border-[var(--accent-2)] bg-[var(--accent-2)]/10"
                        : "border-[var(--border)] bg-[var(--surface-2)] hover:border-[var(--muted)]"
                    }`}
                  >
                    <span className="text-base">{cfg.flag}</span>
                    <span className="flex-1">{cfg.name}</span>
                    {on && <span className="text-[var(--accent-2)]">✓</span>}
                  </button>
                );
              })}
            </div>
            <button
              onClick={submit}
              disabled={submitting || !campaignId.trim() || !markets.length}
              className="w-full rounded-lg bg-[var(--accent)] px-4 py-2.5 text-sm font-semibold text-black transition hover:brightness-110 disabled:cursor-not-allowed disabled:opacity-40"
            >
              {submitting ? phase || "Launching…" : "Trigger Agent Swarm"}
            </button>
            {error && <p className="mt-3 text-xs text-rose-400">{error}</p>}
          </section>

          {/* Stats */}
          <div className="grid grid-cols-3 gap-3">
            {[
              { label: "Total jobs", value: stats.total },
              { label: "Active", value: stats.active },
              { label: "Completed", value: stats.done },
            ].map((s) => (
              <div key={s.label} className="rounded-xl border border-[var(--border)] bg-[var(--surface)] p-4">
                <div className="text-2xl font-semibold">{s.value}</div>
                <div className="text-xs text-[var(--muted)]">{s.label}</div>
              </div>
            ))}
          </div>

          {/* Job list */}
          <section className="rounded-2xl border border-[var(--border)] bg-[var(--surface)] p-2">
            <h2 className="px-3 py-2 text-sm font-semibold">Recent jobs</h2>
            <div className="max-h-[420px] space-y-1 overflow-y-auto px-1 pb-1">
              {jobs.length === 0 && (
                <p className="px-3 py-6 text-center text-xs text-[var(--muted)]">No jobs yet — launch one above.</p>
              )}
              {jobs.map((j) => (
                <button
                  key={j.id}
                  onClick={() => setSelectedId(j.id)}
                  className={`block w-full rounded-lg px-3 py-2.5 text-left transition ${
                    selectedId === j.id ? "bg-[var(--surface-2)]" : "hover:bg-[var(--surface-2)]/60"
                  }`}
                >
                  <div className="flex items-center justify-between">
                    <span className="truncate text-sm font-medium">{j.campaign_id}</span>
                    <StatusBadge status={j.status} />
                  </div>
                  <div className="mt-1 flex items-center justify-between text-[11px] text-[var(--muted)]">
                    <span className="mono">{j.id.slice(0, 8)}</span>
                    <span>
                      {j.markets.length} markets · {timeAgo(j.created_at)}
                    </span>
                  </div>
                </button>
              ))}
            </div>
          </section>
        </div>

        {/* Right column — detail */}
        <div className="lg:col-span-7">
          {!selected ? (
            <div className="flex h-full min-h-[400px] items-center justify-center rounded-2xl border border-dashed border-[var(--border)] text-sm text-[var(--muted)]">
              Select a job to view live agent activity & localized previews.
            </div>
          ) : (
            <div className="space-y-6">
              <section className="rounded-2xl border border-[var(--border)] bg-[var(--surface)] p-5">
                <div className="flex items-center justify-between">
                  <div>
                    <h2 className="text-lg font-semibold">{selected.campaign_id}</h2>
                    <p className="mono mt-0.5 text-xs text-[var(--muted)]">{selected.id}</p>
                  </div>
                  <StatusBadge status={selected.status} />
                </div>
                {selected.error && (
                  <p className="mt-3 rounded-lg border border-rose-500/30 bg-rose-500/10 px-3 py-2 text-xs text-rose-300">
                    {selected.error}
                  </p>
                )}
                <div className="mt-4 flex flex-wrap gap-2">
                  {selected.markets.map((m) => (
                    <span
                      key={m}
                      className="rounded-full border border-[var(--border)] bg-[var(--surface-2)] px-2.5 py-1 text-xs"
                    >
                      {MARKET_CONFIGS[m]?.flag} {MARKET_CONFIGS[m]?.name ?? m}
                    </span>
                  ))}
                </div>
              </section>

              {/* Live logs */}
              <section className="rounded-2xl border border-[var(--border)] bg-[var(--surface)] p-5">
                <h3 className="mb-3 text-sm font-semibold">Live agent log</h3>
                <div
                  ref={logRef}
                  className="mono h-64 overflow-y-auto rounded-lg border border-[var(--border)] bg-black/40 p-3 text-[11px] leading-relaxed text-emerald-200/90"
                >
                  {(selected.logs ?? []).map((line, i) => (
                    <div key={i} className="whitespace-pre-wrap">
                      {line}
                    </div>
                  ))}
                  {(selected.logs ?? []).length === 0 && (
                    <span className="text-[var(--muted)]">Waiting for worker…</span>
                  )}
                </div>
              </section>

              {/* Localized results */}
              {Object.keys(selected.results ?? {}).length > 0 && (
                <section className="rounded-2xl border border-[var(--border)] bg-[var(--surface)] p-5">
                  <h3 className="mb-4 text-sm font-semibold">Localized ad bundles</h3>
                  <div className="grid grid-cols-1 gap-4 sm:grid-cols-2">
                    {Object.entries(selected.results).map(([market, result]) => (
                      <div
                        key={market}
                        className="rounded-xl border border-[var(--border)] bg-[var(--surface-2)] p-3"
                      >
                        <div className="mb-2 flex items-center gap-2 text-sm font-medium">
                          <span>{MARKET_CONFIGS[market]?.flag}</span>
                          {MARKET_CONFIGS[market]?.name ?? market}
                        </div>
                        {previews[market]?.video ? (
                          <video
                            src={previews[market].video}
                            controls
                            className="aspect-video w-full rounded-lg bg-black"
                          />
                        ) : (
                          <div className="flex aspect-video w-full items-center justify-center rounded-lg bg-black/50 text-xs text-[var(--muted)]">
                            preview loading…
                          </div>
                        )}
                        <p className="mono mt-2 truncate text-[10px] text-[var(--muted)]">
                          {result.merged_ad_key}
                        </p>
                      </div>
                    ))}
                  </div>
                </section>
              )}
            </div>
          )}
        </div>
      </div>

      <footer className="mt-12 border-t border-[var(--border)] pt-6 text-center text-xs text-[var(--muted)]">
        Aurora DSQL · Amazon S3 · Next.js on Vercel — H0 Hackathon submission
      </footer>
    </div>
  );
}
