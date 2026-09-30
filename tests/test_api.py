from datetime import datetime, timezone
from fastapi.testclient import TestClient
from astra_api.app import create_app
from astra_pipeline.domain import LATITUDES,LONGITUDES

def artifact():
    panel=[[.1]*121 for _ in range(129)]; cube=[panel]*6
    return {"cycle_id":"cycle-1","generated_at":datetime.now(timezone.utc).isoformat(),"domain":{"latitude":LATITUDES.tolist(),"longitude":LONGITUDES.tolist()},"data_status":{"overall":"degraded","sources":[{"source":"gpm_imerg","provider":"gpm_imerg","state":"complete","mode":"realtime","is_synthetic":False},{"source":"insat_3d_3dr","provider":"mosdac","state":"complete","mode":"realtime","is_synthetic":False},{"source":"synthetic_lightning","provider":"lightning_proxy","state":"synthetic","reason":"proxy","mode":"realtime","is_synthetic":True},{"source":"ground_stations","provider":"meteostat","state":"missing","reason":"Meteostat station coverage sparse","mode":"realtime","is_synthetic":False},{"source":"nwp","provider":"open_meteo","state":"delayed","reason":"late","mode":"realtime","is_synthetic":False}]},"predictions":{"storm_probability":{"lead_minutes":[10,20,30,40,50,60],"values":cube},"lightning_probability":{"lead_minutes":[10,20,30,40,50,60],"values":cube},"storm_confidence":{"lead_minutes":[10,20,30,40,50,60],"values":cube},"lightning_confidence":{"lead_minutes":[10,20,30,40,50,60],"values":cube}},"storms":[]}

def test_complete_sample_provenance_is_rejected(tmp_path):
    app=create_app(audit_database=str(tmp_path/'audit.db'))
    bad=artifact(); bad["data_status"]["sources"][0].update(mode="sample",is_synthetic=True)
    import pytest
    with pytest.raises(ValueError, match="real"):
        app.state.nowcast_store.publish(bad)

def test_startup_rejects_non_file_artifact_path(tmp_path):
    import pytest
    with pytest.raises(RuntimeError, match="existing JSON file"):
        create_app(artifact_path=str(tmp_path / "missing.json"), audit_database=str(tmp_path / "audit.db"))

def test_latest_refuses_missing_cycle_and_serves_full_domain(tmp_path):
    app=create_app(audit_database=str(tmp_path/'audit.db')); client=TestClient(app)
    assert client.get('/api/v1/nowcast/latest').status_code==503
    app.state.nowcast_store.publish(artifact()); response=client.get('/api/v1/nowcast/latest')
    assert response.status_code==200 and response.json()['domain']['latitude']==LATITUDES.tolist()
    assert response.json()['data_status']['overall']=='degraded'
    assert response.json()['data_status']['sources'][1]['provider']=='mosdac'
    assert not any(key in response.text.lower() for key in ['"mock"','"debug"','"sample"'])

def test_read_only_deployment_never_creates_or_updates_audit_state(tmp_path):
    app = create_app(audit_database=str(tmp_path / "audit.db"), read_only=True)
    client = TestClient(app)
    assert client.get("/healthz").json() == {"status": "ok", "nowcast_loaded": False, "write_capability": "unavailable"}
    response = client.post('/api/v1/warnings/warn-1/decision', json={'actor_id':'forecaster-7','decision':'approve'})
    assert response.status_code == 503
    assert response.json()["detail"]["code"] == "READ_ONLY_DEPLOYMENT"
    assert not (tmp_path / "audit.db").exists()

def test_decisions_need_explicit_actor_are_audited_and_never_transmitted(tmp_path):
    app=create_app(audit_database=str(tmp_path/'audit.db')); app.state.warning_repository.create('warn-1',{'tier':'high'}); client=TestClient(app)
    response=client.post('/api/v1/warnings/warn-1/decision',json={'actor_id':'forecaster-7','decision':'approve'})
    assert response.status_code==200 and response.json()['status']=='approved' and response.json()['transmitted'] is False
    audit=client.get('/api/v1/audit/warning-decisions?warning_id=warn-1').json()
    assert len(audit)==1 and audit[0]['actor_id']=='forecaster-7' and audit[0]['decision']=='approve'
