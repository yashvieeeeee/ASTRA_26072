from datetime import datetime, timezone
from fastapi.testclient import TestClient
from astra_api.app import create_app
from astra_pipeline.domain import LATITUDES,LONGITUDES

def artifact():
    panel=[[.1]*121 for _ in range(129)]; cube=[panel]*6
    return {"cycle_id":"cycle-1","generated_at":datetime.now(timezone.utc).isoformat(),"domain":{"latitude":LATITUDES.tolist(),"longitude":LONGITUDES.tolist()},"data_status":{"overall":"degraded","sources":[{"source":"gpm_imerg","state":"complete"},{"source":"insat_3d_3dr","state":"complete"},{"source":"synthetic_lightning","state":"synthetic","reason":"proxy"},{"source":"ground_stations_pending","state":"pending","reason":"source unresolved"},{"source":"nwp","state":"delayed","reason":"late"}]},"predictions":{"storm_probability":{"lead_minutes":[10,20,30,40,50,60],"values":cube},"lightning_probability":{"lead_minutes":[10,20,30,40,50,60],"values":cube},"storm_confidence":{"lead_minutes":[10,20,30,40,50,60],"values":cube},"lightning_confidence":{"lead_minutes":[10,20,30,40,50,60],"values":cube}},"storms":[]}

def test_latest_refuses_missing_cycle_and_serves_full_domain(tmp_path):
    app=create_app(audit_database=str(tmp_path/'audit.db')); client=TestClient(app)
    assert client.get('/api/v1/nowcast/latest').status_code==503
    app.state.nowcast_store.publish(artifact()); response=client.get('/api/v1/nowcast/latest')
    assert response.status_code==200 and response.json()['domain']['latitude']==LATITUDES.tolist()
    assert response.json()['data_status']['overall']=='degraded'
    assert not any(key in response.text.lower() for key in ['"mock"','"debug"','"sample"'])

def test_decisions_need_explicit_actor_are_audited_and_never_transmitted(tmp_path):
    app=create_app(audit_database=str(tmp_path/'audit.db')); app.state.warning_repository.create('warn-1',{'tier':'high'}); client=TestClient(app)
    response=client.post('/api/v1/warnings/warn-1/decision',json={'actor_id':'forecaster-7','decision':'approve'})
    assert response.status_code==200 and response.json()['status']=='approved' and response.json()['transmitted'] is False
    audit=client.get('/api/v1/audit/warning-decisions?warning_id=warn-1').json()
    assert len(audit)==1 and audit[0]['actor_id']=='forecaster-7' and audit[0]['decision']=='approve'
