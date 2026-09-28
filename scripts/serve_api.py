import os
import uvicorn
# ASTRA_NOWCAST_ARTIFACT must point at a validated, real Phase 3+4 JSON artifact.
uvicorn.run("astra_api.app:app",host=os.getenv("ASTRA_API_HOST","127.0.0.1"),port=int(os.getenv("ASTRA_API_PORT","8000")),reload=False)
