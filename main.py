"""Navoiyazot Logistics: AI Dispatcher Standalone Service."""
import logging
import uvicorn
from fastapi import FastAPI
from atil_ai_dispetcher.router import router as dispatcher_router
from atil_ai_dispetcher.app import start as dispatch_start, stop as dispatch_stop

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(name)s: %(message)s")

app = FastAPI(
    title="Navoiyazot Logistics · AI Dispatcher API",
    description="Automated freight vehicle dispatching, order matching, and GPS yard monitoring for Navoiyazot plant.",
    version="1.0.0"
)

app.include_router(dispatcher_router)

@app.on_event("startup")
async def on_startup():
    await dispatch_start()

@app.on_event("shutdown")
async def on_shutdown():
    await dispatch_stop()

@app.get("/healthz", tags=["Health"])
async def healthz():
    return {"status": "ok", "service": "ai-dispatcher"}

if __name__ == "__main__":
    uvicorn.run("main:app", host="0.0.0.0", port=8001, reload=False)
