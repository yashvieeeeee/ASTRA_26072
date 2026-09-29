import { apiUrl } from "./client";

export type LightningCorroboration = {
  provider: "weatherbit";
  classification: "live_third_party_corroboration_not_model_input";
  search_distance_km: number;
  search_mins: number;
  event_count: number;
  observations: Array<{ id: number | null; lat: number | null; lon: number | null; timestamp_utc: string | null; type: string | null; source: string | null }>;
};

export class LightningLookupError extends Error {
  constructor(public readonly code: string, message: string) { super(message); }
}

export async function fetchLightningCorroboration(latitude: number, longitude: number, signal?: AbortSignal): Promise<LightningCorroboration> {
  const query = new URLSearchParams({ latitude: String(latitude), longitude: String(longitude) });
  const response = await fetch(apiUrl(`/api/v1/lightning/corroboration?${query}`), { signal, headers: { Accept: "application/json" } });
  if (!response.ok) {
    const body = await response.json().catch(() => null) as { detail?: { code?: string; message?: string } } | null;
    throw new LightningLookupError(body?.detail?.code ?? "UNAVAILABLE", body?.detail?.message ?? "Live third-party corroboration is unavailable.");
  }
  return response.json() as Promise<LightningCorroboration>;
}
