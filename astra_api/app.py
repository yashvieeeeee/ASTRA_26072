from __future__ import annotations
import os
from pathlib import Path
from fastapi import FastAPI, HTTPException, Query
from .schemas import NowcastResponse, WarningDecisionRequest, WarningDraft, AuditEvent
from .store import NowcastStore, WarningRepository

def create_app(*, artifact_path: str|None=None, audit_database: str|None=None):
    """Production API factory. It never generates samples or exposes diagnostic routes."""
    app=FastAPI(title="ASTRA Nowcast API",version="1.0.0",openapi_url="/openapi.json",docs_url="/docs")
    store=NowcastStore(); repository=WarningRepository(audit_database or os.getenv("ASTRA_AUDIT_DB","astra_audit.sqlite3"))
    artifact=artifact_path or os.getenv("ASTRA_NOWCAST_ARTIFACT")
    if artifact:
        path = Path(artifact)
        if not path.is_file():
            raise RuntimeError(f"ASTRA_NOWCAST_ARTIFACT must be an existing JSON file; got {path}")
        store.load_json(path)
    app.state.nowcast_store=store; app.state.warning_repository=repository

    @app.get("/api/v1/nowcast/latest",response_model=NowcastResponse,responses={503:{"description":"No real Phase 3+4 cycle is published"}})
    def latest_nowcast():
        response=store.latest()
        if response is None: raise HTTPException(503,detail={"code":"NO_CURRENT_CYCLE","message":"No real Phase 3+4 artifact has been published."})
        return response
    @app.get("/api/v1/warnings/drafts",response_model=list[WarningDraft])
    def list_drafts(): return repository.drafts()
    @app.post("/api/v1/warnings/{warning_id}/decision",response_model=WarningDraft)
    def warning_decision(warning_id: str, request: WarningDecisionRequest):
        try: warning=repository.decide(warning_id,request)
        except ValueError as exc: raise HTTPException(409,detail=str(exc))
        if warning is None: raise HTTPException(404,detail="Warning draft not found")
        return warning
    @app.get("/api/v1/audit/warning-decisions",response_model=list[AuditEvent])
    def warning_audit(warning_id: str|None=None, limit: int=Query(100,ge=1,le=1000)): return repository.audit(warning_id,limit)
    return app

app=create_app()
