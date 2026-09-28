from __future__ import annotations
from datetime import datetime,timezone
import json,sqlite3,threading
from pathlib import Path
from .schemas import NowcastResponse, WarningDraft, WarningDecisionRequest, AuditEvent, SourceState

REQUIRED_SOURCES={"gpm_imerg","insat_3d_3dr","synthetic_lightning","ground_stations_pending","nwp"}
class NowcastStore:
    def __init__(self): self._latest=None; self._lock=threading.Lock()
    def publish(self, artifact: dict|NowcastResponse):
        parsed=artifact if isinstance(artifact,NowcastResponse) else NowcastResponse.model_validate(artifact)
        names={source.source for source in parsed.data_status.sources}
        if names != REQUIRED_SOURCES: raise ValueError(f"Source status must include exactly five sources; got {names}")
        states={source.state for source in parsed.data_status.sources}; expected="complete" if states=={SourceState.complete} else "degraded"
        if parsed.data_status.overall not in (expected,"stale"): raise ValueError(f"overall must be {expected!r} or stale, never silently complete")
        with self._lock: self._latest=parsed
    def latest(self):
        with self._lock: return self._latest
    def load_json(self,path): self.publish(json.loads(Path(path).read_text()))

class WarningRepository:
    def __init__(self, database_path: str):
        self.connection=sqlite3.connect(database_path,check_same_thread=False); self.lock=threading.Lock()
        with self.connection:
            self.connection.execute("CREATE TABLE IF NOT EXISTS warnings (warning_id TEXT PRIMARY KEY, status TEXT NOT NULL, payload TEXT NOT NULL, created_at TEXT NOT NULL, decided_at TEXT, decided_by TEXT)")
            self.connection.execute("CREATE TABLE IF NOT EXISTS warning_audit (id INTEGER PRIMARY KEY AUTOINCREMENT, warning_id TEXT NOT NULL, actor_id TEXT NOT NULL, decision TEXT NOT NULL, occurred_at TEXT NOT NULL, edit TEXT)")
    @staticmethod
    def _now(): return datetime.now(timezone.utc)
    def create(self,warning_id,payload):
        now=self._now()
        with self.connection: self.connection.execute("INSERT INTO warnings VALUES (?,?,?,?,?,?)",(warning_id,"draft",json.dumps(payload),now.isoformat(),None,None))
        return self.get(warning_id)
    def get(self,warning_id):
        row=self.connection.execute("SELECT * FROM warnings WHERE warning_id=?",(warning_id,)).fetchone()
        if not row: return None
        return WarningDraft(warning_id=row[0],status=row[1],payload=json.loads(row[2]),created_at=datetime.fromisoformat(row[3]),decided_at=datetime.fromisoformat(row[4]) if row[4] else None,decided_by=row[5])
    def drafts(self): return [self.get(row[0]) for row in self.connection.execute("SELECT warning_id FROM warnings WHERE status='draft' ORDER BY created_at DESC")]
    def decide(self,warning_id,request: WarningDecisionRequest):
        with self.lock, self.connection:
            current=self.get(warning_id)
            if not current: return None
            if current.status!="draft": raise ValueError("Warning already decided; create a revised draft instead")
            now=self._now(); status={"approve":"approved","edit":"edited","dismiss":"dismissed"}[request.decision.value]
            payload=current.payload if request.edit is None else {**current.payload,**request.edit}
            self.connection.execute("UPDATE warnings SET status=?,payload=?,decided_at=?,decided_by=? WHERE warning_id=?",(status,json.dumps(payload),now.isoformat(),request.actor_id,warning_id))
            self.connection.execute("INSERT INTO warning_audit(warning_id,actor_id,decision,occurred_at,edit) VALUES (?,?,?,?,?)",(warning_id,request.actor_id,request.decision.value,now.isoformat(),json.dumps(request.edit) if request.edit else None))
        return self.get(warning_id)
    def audit(self,warning_id=None,limit=100):
        sql="SELECT warning_id,actor_id,decision,occurred_at,edit FROM warning_audit"; args=[]
        if warning_id: sql+=" WHERE warning_id=?"; args.append(warning_id)
        sql+=" ORDER BY id DESC LIMIT ?"; args.append(limit)
        return [AuditEvent(warning_id=row[0],actor_id=row[1],decision=row[2],occurred_at=datetime.fromisoformat(row[3]),edit=json.loads(row[4]) if row[4] else None) for row in self.connection.execute(sql,args)]
