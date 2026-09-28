export type WarningDecision = "approve" | "edit" | "dismiss";
export interface WarningDraft { warning_id: string; status: string; payload: Record<string, unknown>; created_at: string; decided_at: string | null; decided_by: string | null; transmitted: false; }
export interface AuditEvent { warning_id: string; actor_id: string; decision: WarningDecision; occurred_at: string; edit: Record<string, unknown> | null; }
async function request<T>(path: string, options?: RequestInit): Promise<T> {
  const response = await fetch(path, { headers: { Accept: "application/json", "Content-Type": "application/json", ...options?.headers }, ...options });
  if (!response.ok) throw new Error((await response.text()) || `Request failed (${response.status})`);
  return response.json() as Promise<T>;
}
export const fetchWarningDrafts = () => request<WarningDraft[]>("/api/v1/warnings/drafts");
export const fetchWarningAudit = () => request<AuditEvent[]>("/api/v1/audit/warning-decisions");
export const decideWarning = (warningId: string, actorId: string, decision: WarningDecision, edit?: Record<string, unknown>) => request<WarningDraft>(`/api/v1/warnings/${encodeURIComponent(warningId)}/decision`, { method: "POST", body: JSON.stringify({ actor_id: actorId, decision, edit }) });
