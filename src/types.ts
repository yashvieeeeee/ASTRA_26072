export type Mode = "Overview" | "Storms" | "Nowcast" | "Risk" | "Warnings" | "Infrastructure" | "Data" | "Audit";
export type Layer = "Probability" | "Lightning" | "Tracks" | "Risk fields" | "Infrastructure";
export type WarningState = "list" | "review" | "confirm" | "approved";
export type WarningDraft = { warning_id: string; status: string; payload: Record<string, unknown>; created_at: string; decided_at: string | null; decided_by: string | null; transmitted: false };
export type AuditEvent = { warning_id: string; actor_id: string; decision: "approve" | "edit" | "dismiss"; occurred_at: string; edit: Record<string, unknown> | null };
export type StormLead = { minutes: number; probability: number | null; lightning: number | null; confidence: number | null };
export type Storm = { id: string; x: number; y: number; latitude: number; longitude: number; directionDegrees: number; motionSpeedKmH: number; trend: string; risk: "SEVERE" | "HIGH" | "MODERATE" | "LOW"; probability: number; lightning: number; confidence: number; speed: number; eta: number | null; place: string; impactIndex: number; attribution: Record<string, number>; facilities: number; leads: StormLead[] };
