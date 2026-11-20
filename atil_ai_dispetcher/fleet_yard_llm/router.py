"""One public plate-based endpoint for garage and fleet monitoring."""

import json
import asyncio
import logging
import threading
import time
from pathlib import Path

from fastapi import APIRouter, HTTPException, Header
from fastapi.concurrency import run_in_threadpool
from fastapi.encoders import jsonable_encoder
from fastapi.responses import StreamingResponse

from atil_ai_dispetcher.fleet_yard_llm import monitor, monitor_ai, queries
from atil_ai_dispetcher.fleet_yard_llm.monitor_models import MonitorRequest, MonitorReport

router = APIRouter(prefix="/fleet-yard", tags=["GPS garaj va avtopark"])
logger = logging.getLogger(__name__)


async def _calculate(request, cancelled=None):
    try:
        if cancelled is None:
            return await run_in_threadpool(monitor.report, request)
        return await run_in_threadpool(monitor.report, request, cancelled=cancelled)
    except queries.VehicleNotFound as exc:
        raise HTTPException(404, "Bunday raqamli transport topilmadi") from exc
    except queries.AmbiguousPlate as exc:
        raise HTTPException(409, str(exc)) from exc
    except queries.YardDataError as exc:
        raise HTTPException(503, str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(422, str(exc)) from exc


async def _events(request):
    """Same endpoint, optional progress transport; default clients receive JSON."""
    stage = "gps"
    cancelled = threading.Event()
    started = time.monotonic()

    async def produce():
        nonlocal stage
        result = await _calculate(request, cancelled)
        stage = "ai" if request.analyze else "report"
        await monitor_ai.enrich(result, request.analyze)
        return jsonable_encoder(MonitorReport(**result))

    def event(kind, data):
        return "event: " + kind + "\ndata: " + json.dumps(data, ensure_ascii=False, allow_nan=False) + "\n\n"

    task = asyncio.create_task(produce())
    try:
        while not task.done():
            yield event("progress", {"stage": stage, "elapsed_seconds": round(time.monotonic()-started)})
            await asyncio.wait({task}, timeout=10)
        yield event("report", await task)
    except HTTPException as exc:
        yield event("error", {"status": exc.status_code, "detail": exc.detail})
    except Exception as exc:
        logger.warning("Monitoring stream failed: %s", type(exc).__name__)
        yield event("error", {"status": 500, "detail": "Hisobotni hisoblashda xato yuz berdi; qayta urinib ko'ring."})
    finally:
        cancelled.set()
        if not task.done():
            task.cancel()
        try:
            await task
        except BaseException:
            pass


@router.post(
    "/monitor", response_model=MonitorReport,
    summary="Garaj va avtopark: raqam bo'yicha yoki barcha transportlar, bitta hisobot",
    openapi_extra={"requestBody": {"content": {"application/json": {"example": json.loads(
        Path(__file__).with_name("example_request.json").read_text(encoding="utf-8"))}}}},
    responses={404: {"description": "Transport raqami topilmadi"},
               409: {"description": "Raqam bir nechta transportda takrorlangan"},
               503: {"description": "Bazadan to'liq o'qib bo'lmadi"}},
)
async def monitor_fleet(request: MonitorRequest, accept: str | None = Header(default=None)):
    """Garaj koordinatalari majburiy; `plate_number` bo'sh bo'lsa butun flot.

    `days=60` da 1/7/15/30/60 kunlik kesimlar qaytadi. `as_of` berilmasa hozir.
    Xabarlar `alerts` ichida, GPSsiz holatlar noma'lum. Tirbandlik ehtimol.
    AI ishlamasa hisob saqlanadi, `analysis.status=UNAVAILABLE` qaytadi.
    Bazaga yozish, status o'zgartirish yoki tashqi xabar jo'natish yo'q.
    """
    if accept and "text/event-stream" in accept.lower():
        return StreamingResponse(_events(request), media_type="text/event-stream",
            headers={"Cache-Control": "no-cache, no-transform", "X-Accel-Buffering": "no"})
    result = await _calculate(request)
    await monitor_ai.enrich(result, request.analyze)
    return MonitorReport(**result)

