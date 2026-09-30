import os
import sys
from pathlib import Path
import uvicorn

# Running this file directly otherwise adds only ``scripts/`` to sys.path.
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
# ASTRA_NOWCAST_ARTIFACT must point at a validated, real Phase 3+4 JSON artifact.
uvicorn.run("astra_api.app:app",host=os.getenv("ASTRA_API_HOST","127.0.0.1"),port=int(os.getenv("ASTRA_API_PORT","8000")),reload=False)
