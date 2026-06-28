export type JobStatus =
  | "initializing"
  | "security-scanning"
  | "forking"
  | "processing"
  | "assembling"
  | "completed"
  | "failed";

export interface AgentState {
  status: string;
  updated_at: string;
}

export interface MarketResult {
  market: string;
  merged_ad_key: string;
  localized_video_key: string;
  localized_audio_key: string;
  output_bucket: string;
}

export interface LocalizationJob {
  id: string;
  campaign_id: string;
  status: JobStatus;
  markets: string[];
  video_key: string;
  audio_key: string;
  source_bucket: string;
  forks: Record<string, string>;
  agents: Record<string, AgentState>;
  results: Record<string, MarketResult>;
  logs: string[];
  error: string | null;
  created_at: string;
  updated_at: string;
}
