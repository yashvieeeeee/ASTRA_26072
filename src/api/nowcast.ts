export type SourceHealthState = "complete" | "delayed" | "missing" | "synthetic" | "pending";

export interface LatestNowcastResponse {
  cycle_id: string;
  generated_at: string;
  domain: { latitude: number[]; longitude: number[]; resolution_degrees: number };
  data_status: {
    overall: string;
    sources: Array<{ source: string; state: SourceHealthState; observed_at: string | null; reason: string | null }>;
  };
  predictions: {
    storm_probability: ProbabilityCube;
    lightning_probability: ProbabilityCube;
    storm_confidence: ProbabilityCube;
    lightning_confidence: ProbabilityCube;
  };
  storms: TrackedStorm[];
}

interface ProbabilityCube {
  lead_minutes: number[];
  values: number[][][];
}

export interface TrackedStorm {
  track_id: string;
  latitude: number;
  longitude: number;
  velocity: { speed_km_h: number; direction_degrees: number };
  trend: string;
  probability: number;
  confidence: number;
  tier: string;
  impact_index: number;
  source_attribution: Record<string, number>;
  affected_areas: string[];
  exposed_infrastructure: Array<Record<string, unknown>>;
}

export async function fetchLatestNowcast(signal?: AbortSignal): Promise<LatestNowcastResponse> {
  const response = await fetch("/api/v1/nowcast/latest", { signal, headers: { Accept: "application/json" } });
  if (!response.ok) {
    throw new Error(response.status === 503 ? "No live nowcast cycle is available yet." : `Latest nowcast request failed (${response.status}).`);
  }
  const nowcast = await response.json() as LatestNowcastResponse;
  const { latitude, longitude } = nowcast.domain;
  if (Math.min(...latitude) !== 6 || Math.max(...latitude) !== 38 || Math.min(...longitude) !== 68 || Math.max(...longitude) !== 98) {
    throw new Error("The latest nowcast is not scoped to the required full pan-India domain (6–38°N, 68–98°E).");
  }
  return nowcast;
}
