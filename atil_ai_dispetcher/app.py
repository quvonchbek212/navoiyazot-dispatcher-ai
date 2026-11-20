"""Run from repository root: python -m uvicorn atil_ai_dispetcher.app:app --port 8020"""
from contextlib import asynccontextmanager
from fastapi import FastAPI, Depends
from fastapi.responses import RedirectResponse
from atil_ai_dispetcher import config
from atil_ai_dispetcher.store import Store
from atil_ai_dispetcher.worker import Worker
from atil_ai_dispetcher.router import router
from security import require_api_credentials

async def start(app):
    app.state.dispatch_store=Store(config.STATE_PATH)
    app.state.dispatch_store.migrate_v2()
    app.state.dispatch_worker=Worker(app.state.dispatch_store)
    app.state.dispatch_worker.start()

async def stop(app):await app.state.dispatch_worker.stop()

@asynccontextmanager
async def lifespan(app):
    await start(app)
    yield
    await stop(app)

app=FastAPI(title='ATIL AI Dispetcher',version='2.0.0',lifespan=lifespan)
app.include_router(router)

# The single dispatcher API is the only active contract. Retired engines are
# not imported, scheduled, or exposed through this application.

@app.get('/',include_in_schema=False)
def root():return RedirectResponse('/ai-dispatcher/')

@app.middleware('http')
async def security_headers(request,call_next):
    response=await call_next(request)
    response.headers['X-Content-Type-Options']='nosniff'
    response.headers['Referrer-Policy']='same-origin'
    response.headers['X-Frame-Options']='DENY'
    if request.url.path.startswith('/ai-dispatcher'):
        response.headers['Content-Security-Policy']="default-src 'self'; script-src 'self'; style-src 'self'; img-src 'self' data:; connect-src 'self'; frame-ancestors 'none'; base-uri 'self'; form-action 'self'"
        response.headers['Cache-Control']='no-store'
    return response
