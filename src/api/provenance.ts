import type { LatestNowcastResponse } from "./nowcast";

export type SourceStatus = LatestNowcastResponse["data_status"]["sources"][number];

const labelTime = (value: string | null | undefined) => value ? new Intl.DateTimeFormat("en-IN", { timeZone: "Asia/Kolkata", hour: "2-digit", minute: "2-digit", hour12: false }).format(new Date(value)) + " IST" : "TIME UNAVAILABLE";

export function sourceLabel(source: SourceStatus) {
  const demo = source.mode === "sample" || source.provider === "demo" || source.provider?.startsWith("demo-") || source.state === "synthetic" && source.provider === "demo";
  const synthetic = source.is_synthetic === true || source.state === "synthetic";
  // Demo provider and sample mode describe the same scenario, so collapse them
  // into one unambiguous phrase instead of rendering "DEMO" twice.
  if (demo) return `DEMO SCENARIO · OBS ${labelTime(source.observed_at)}`;

  const tokens = [synthetic ? "SYNTHETIC" : "REAL", source.provider?.toUpperCase(), source.mode?.toUpperCase()]
    .filter((token): token is string => Boolean(token))
    .filter((token, index, values) => values.findIndex((value) => value === token) === index);
  return `${tokens.join(" · ")} · OBS ${labelTime(source.observed_at)}`;
}

export function provenanceFor(sources: SourceStatus[], kind: "forecast" | "lightning") {
  const matches = sources.filter((source) => kind === "lightning" ? /lightning/i.test(`${source.source} ${source.provider ?? ""}`) : true);
  const selected = matches.length ? matches : sources;
  return [...new Set(selected.map(sourceLabel))].join(" | ") || "SOURCE STATUS UNAVAILABLE";
}
