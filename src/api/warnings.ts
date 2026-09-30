export type WarningDecision = "approve" | "edit" | "dismiss";
import { apiUrl, shouldUseMock } from "./client";
import { mockAudit, mockDrafts } from "./mock";
export interface WarningDraft { warning_id: string; status: string; payload: Record<string, unknown>; created_at: string; decided_at: string | null; decided_by: string | null; transmitted: false; }
export interface AuditEvent { warning_id: string; actor_id: string; decision: WarningDecision; occurred_at: string; edit: Record<string, unknown> | null; }
async function request<T>(path: string, options?: RequestInit): Promise<T> {
  const response = await fetch(path, { headers: { Accept: "application/json", "Content-Type": "application/json", ...options?.headers }, ...options });
  if (!response.ok) throw new Error((await response.text()) || `Request failed (${response.status})`);
  return response.json() as Promise<T>;
}
export async function fetchWarningDrafts() { try { if (shouldUseMock() && !apiUrl("")) return mockDrafts; return await request<WarningDraft[]>(apiUrl("/api/v1/warnings/drafts")); } catch (error) { if (shouldUseMock()) return mockDrafts; throw error; } }
export async function fetchWarningAudit() { try { if (shouldUseMock() && !apiUrl("")) return mockAudit; return await request<AuditEvent[]>(apiUrl("/api/v1/audit/warning-decisions")); } catch (error) { if (shouldUseMock()) return mockAudit; throw error; } }
export async function decideWarning(warningId: string, actorId: string, decision: WarningDecision, edit?: Record<string, unknown>) { try { if (!shouldUseMock() || apiUrl("")) return await request<WarningDraft>(apiUrl(`/api/v1/warnings/${encodeURIComponent(warningId)}/decision`), { method: "POST", body: JSON.stringify({ actor_id: actorId, decision, edit }) }); } catch (error) { if (!shouldUseMock()) throw error; } const index = mockDrafts.findIndex((draft) => draft.warning_id === warningId); const draft = mockDrafts[index]; if (!draft) throw new Error("Warning draft not found."); if (decision === "edit") mockDrafts[index] = { ...draft, payload: { ...draft.payload, ...edit } }; else mockDrafts.splice(index, 1); mockAudit.unshift({ warning_id: warningId, actor_id: actorId, decision, occurred_at: new Date().toISOString(), edit: edit ?? null }); return draft; }
