"""Local fleet dashboard. Only the existing read-only fleet API is exposed.

Run: python -m uvicorn atil_ai_dispetcher.fleet_yard_llm.web:app --host 127.0.0.1 --port 8010
This app has no startup workers, migrations, or database writes.
"""

from pathlib import Path

from fastapi import FastAPI, Security
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from atil_ai_dispetcher.fleet_yard_llm.router import router
from security import require_api_credentials

FRONTEND = Path(__file__).with_name("frontend")
app = FastAPI(title="ATIL Fleet — boshqaruv paneli", docs_url=None, redoc_url=None)
app.include_router(router, dependencies=[Security(require_api_credentials)])
app.mount("/assets", StaticFiles(directory=FRONTEND), name="fleet-assets")


@app.get("/", include_in_schema=False)
def dashboard() -> FileResponse:
    return FileResponse(FRONTEND / "index.html", headers={"Cache-Control": "no-cache"})
