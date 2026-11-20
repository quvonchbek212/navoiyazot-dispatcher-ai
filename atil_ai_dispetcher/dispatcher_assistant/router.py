"""Dispetcher yordamchisi — to'rtta endpoint.

Router `main.py` dagi yagona FastAPI ilovasiga ulanadi — bu yerda
alohida `FastAPI()` yaratilmaydi. Butun ilova HTTP Basic bilan yopiq
(`security.py`).

NIMA UCHUN TO'RTTA ENDPOINT, BITTA HISOBOT EMAS:

  * har biri o'z ro'yxatini qaytaradi va ro'yxatlar uzun bo'ladi —
    bitta javobga yig'ilsa dispetcher kerakli narsani qidirib o'tirardi;
  * panel har bo'limni ALOHIDA yangilay oladi: kechikish har daqiqada
    o'zgaradi, hujjat muddati esa kuniga bir marta;
  * har biri o'z filtri bilan chaqiriladi (`min_minutes`, `min_meters`,
    `days`) — umumiy hisobotda ular aralashib ketardi;
  * telematika o'chganda faqat ikkitasi bo'sh qaytadi, qolgan ikkitasi
    ishlayveradi.

FILTRLAR SUKUT BO'YICHA O'CHIQ. `min_minutes`, `min_meters`, `days` —
hech biri majburiy emas va hech birining sukut qiymati yo'q. Sababi:
"30 daqiqadan ortiq kechikish muhim" degan raqamni baza aytmaydi.
Ro'yxat og'irligi bo'yicha saralangan holda to'liq qaytadi, kesish
qarori chaqiruvchida.
"""

from __future__ import annotations

import logging
from typing import Literal
from datetime import date

from fastapi import APIRouter, HTTPException, Query
from fastapi.concurrency import run_in_threadpool

from atil_ai_dispetcher.dispatcher_assistant import config, service, texts
from atil_ai_dispetcher.dispatcher_assistant.explain import analyze, fill_template
from atil_ai_dispetcher.dispatcher_assistant.models import (
    DelayedReport,
    DeviationReport,
    DocumentsReport,
    IdleReport,
)
from atil_ai_dispetcher.dispatcher_assistant.queries import DispatcherDataError

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/dispatcher", tags=["Dispetcher yordamchisi"])

_ANALYZE = Query(
    None, alias="analyze",
    description="Xulosani LLM yozsinmi. Berilmasa `.env` dagi `DA_LLM_ANALYZE`. "
                "**LLM javobni 10-20 soniyaga cho'zadi** — ro'yxat o'zgarmaydi, "
                "shoshilinch so'rovda `false` qilingani ma'qul.",
)

#: Uchala endpointda bir xil ko'rinishi uchun.
_LANG = Query(
    "uz",
    description="**Javob tili.** `data_quality.notes`, `summary.worst` va "
                "xulosa (`analysis`) shu tilda chiqadi.\n\n"
                "**Kodlar tarjima qilinmaydi**: `kind` (`NOT_DEPARTED`, "
                "`LATE_EN_ROUTE`), `document_type`, `subject_type`, jadval va "
                "ustun nomlari uch tilda ham bir xil.",
)

_LIMIT = Query(
    config.DEFAULT_LIMIT, ge=1, le=config.MAX_LIMIT,
    description="Nechta qator qaytsin. `summary.total` da chegaradan oldingi "
                "to'liq son turadi.",
)


async def _finish(
    report: dict, kind: str, use_llm: bool | None, lang: str = texts.DEFAULT_LANG
):
    fill_template(report, kind, lang)
    if config.LLM_ANALYZE if use_llm is None else use_llm:
        # Xato bo'lsa ham hisobot qaytadi — xulosa shablon bo'lib qoladi.
        await analyze(report, kind, lang=lang)
    return report


# =========================================================== 1. Kechikish


@router.get(
    "/delayed",
    response_model=DelayedReport,
    summary="Kechikayotgan reyslar",
    responses={503: {"description": "Bazaga ulanib bo'lmadi"}},
)
async def delayed(
    min_minutes: float | None = Query(
        None, ge=0,
        description="Shuncha daqiqadan ko'p kechikkanlar. **Berilmasa hammasi** — "
                    "\"muhim kechikish\" degan meyor bazada yo'q, shuning uchun "
                    "o'ylab topilmadi.",
    ),
    kind: str | None = Query(
        None,
        description="`NOT_DEPARTED` — jo'nash vaqti o'tgan, hali chiqmagan. "
                    "`LATE_EN_ROUTE` — yo'lda, yetib borish vaqti o'tgan. "
                    "Berilmasa ikkalasi ham.",
        examples=["NOT_DEPARTED"],
    ),
    limit: int = _LIMIT,
    analyze_result: bool | None = _ANALYZE,
    lang: Literal["uz", "ru", "en"] = _LANG,
) -> DelayedReport:
    """Muddatidan orqada qolgan **aktiv reyslar**.

    **Ikki xil kechikish ajratiladi** — bu bir xil vaziyat emas:

    | `kind` | Ma'nosi | Dispetcher nima qila oladi |
    |---|---|---|
    | `NOT_DEPARTED` | jo'nash vaqti o'tgan, mashina hali chiqmagan | hali to'xtata oladi, boshqa mashina bera oladi |
    | `LATE_EN_ROUTE` | yo'lda, yetib borish vaqti o'tgan | faqat mijozni ogohlantirish qoladi |

    **Kechikish meyor emas, solishtirish:** `scheduled_departure_at` yoki
    `scheduled_arrival_at` hozirgi vaqtdan oldinmi. Kodda "30 daqiqa" kabi
    o'ylab topilgan chegara yo'q.

    Har qatorda **oxirgi `trip_event`** ko'rsatiladi — reys qayerda
    to'xtab qolganini shu aytadi (yuklashda kutyaptimi, yo'lga chiqdimi).

    **Bazaga ta'sir:** faqat `SELECT`, READ ONLY tranzaksiyada.
    """
    try:
        report = await run_in_threadpool(
            service.delayed, min_minutes=min_minutes, kind=kind, limit=limit,
            lang=lang,
        )
    except DispatcherDataError as exc:
        raise HTTPException(503, f"Bazadan o'qib bo'lmadi: {exc}")
    return DelayedReport(**await _finish(report, "delayed", analyze_result, lang))


# ================================================= 2. Yo'nalishdan og'ish


@router.get(
    "/deviations",
    response_model=DeviationReport,
    summary="Yo'nalishdan og'ayotgan mashinalar",
    responses={503: {"description": "Bazaga ulanib bo'lmadi"}},
)
async def deviations(
    min_meters: float | None = Query(
        None, ge=0,
        description="Yo'ldan shuncha metrdan uzoq chetlanganlar. Berilmasa "
                    "hammasi. **Masofasi o'lchanmaganlar bu filtr bilan "
                    "kesilmaydi** — \"o'lchanmadi\" ni \"chetlanmagan\" deb "
                    "hisoblash xato bo'lardi.",
    ),
    limit: int = _LIMIT,
    analyze_result: bool | None = _ANALYZE,
    lang: Literal["uz", "ru", "en"] = _LANG,
) -> DeviationReport:
    """Rejadagi yo'ldan chiqib ketgan mashinalar.

    **Og'ishni bu endpoint aniqlamaydi.** Uni telematika xizmati
    aniqlaydi va `vehicle_telemetry_state.deviation_active` ga yozadi;
    chegara ham bazada — `deviation_threshold_meters`. Bu yerda o'sha
    natija o'qiladi va odam o'qiydigan holga keltiriladi.

    Nima uchun qayta hisoblanmaydi: telematika xizmati har bir GPS
    nuqtasini ko'radi, bu endpoint esa faqat oxirgi holatni. Qayta
    hisoblansa kamroq ma'lumot bilan boshqa javob chiqib, ikki xil
    haqiqat paydo bo'lardi.

    **Qo'shimcha o'lchov:** `distance_from_route_meters` — mashinaning
    hozirgi nuqtasidan rejadagi yo'lgacha bo'lgan masofa. Nuqtadan
    NUQTAGACHA emas, **kesmagacha** o'lchanadi: ikki nuqta o'rtasida
    ketayotgan mashina aks holda yo'ldan chiqqandek ko'rinardi.

    Marshrut nuqtalari `route_points_json` dan, u bo'sh bo'lsa
    `route_point` dan olinadi. Ikkalasi ham bo'lmasa masofa `null`
    bo'ladi — nol emas.
    """
    try:
        report = await run_in_threadpool(
            service.deviations, min_meters=min_meters, limit=limit, lang=lang
        )
    except DispatcherDataError as exc:
        raise HTTPException(503, f"Bazadan o'qib bo'lmadi: {exc}")
    return DeviationReport(**await _finish(report, "deviations", analyze_result, lang))


# ========================================================= 3. Bekor turish


@router.get(
    "/idle",
    response_model=IdleReport,
    summary="Bekor turgan mashinalar",
    responses={503: {"description": "Bazaga ulanib bo'lmadi"}},
)
async def idle(
    min_minutes: float | None = Query(
        None, ge=0,
        description="Shuncha daqiqadan ko'p turganlar. **Berilmasa hammasi** — "
                    "\"uzoq to'xtash\" degan meyor bazada yo'q. Ro'yxat "
                    "davomiylik bo'yicha saralangan, eng uzog'i tepada.",
    ),
    limit: int = _LIMIT,
    analyze_result: bool | None = _ANALYZE,
    lang: Literal["uz", "ru", "en"] = _LANG,
) -> IdleReport:
    """Uzoq to'xtab qolgan mashinalar — eng uzog'i birinchi.

    To'xtash faktini telematika xizmati belgilaydi
    (`vehicle_telemetry_state.stop_active`), bu yerda **davomiylik**
    hisoblanadi: `now() - stop_candidate_since`.

    **Dvigatel holati alohida qaraladi.** `engine_on=true` bo'lsa mashina
    turib yoqilg'i yoqyapti — bu boshqa vaziyat, va `summary.by_kind` da
    alohida sanaladi (`ENGINE_ON` / `ENGINE_OFF` / `UNKNOWN`).

    **`minutes_since_last_event` ga e'tibor bering.** GPS uzilib qolgan
    mashina ham "to'xtagan" bo'lib ko'rinadi. Bu maydon ikkalasini
    ajratadi: oxirgi yozuv 3 soat oldin bo'lsa, mashina turgani emas,
    **aloqa yo'qligi** ehtimoli katta.
    """
    try:
        report = await run_in_threadpool(
            service.idle, min_minutes=min_minutes, limit=limit, lang=lang
        )
    except DispatcherDataError as exc:
        raise HTTPException(503, f"Bazadan o'qib bo'lmadi: {exc}")
    return IdleReport(**await _finish(report, "idle", analyze_result, lang))


# ======================================================= 4. Hujjat muddati


@router.get(
    "/documents",
    response_model=DocumentsReport,
    summary="Hujjati tugayotgan haydovchi va mashinalar",
    responses={503: {"description": "Bazaga ulanib bo'lmadi"}},
)
async def documents(
    days: int | None = Query(
        None,
        description="Shuncha kun ichida tugaydiganlar (masalan `30`). "
                    "**Berilmasa hammasi** — \"necha kun qolgani xavfli\" "
                    "degan raqam bazada yo'q. Muddati o'tganlar oynadan "
                    "qat'i nazar HAR DOIM ro'yxatda bo'ladi.",
        examples=[30],
    ),
    subject_type: str | None = Query(
        None, description="`DRIVER` yoki `VEHICLE`", examples=["DRIVER"]),
    document_type: str | None = Query(
        None,
        description="`LICENSE`, `MEDICAL_CERTIFICATE`, `CREDENTIAL`, "
                    "`VEHICLE_DOCUMENT`, `INSURANCE`",
        examples=["LICENSE"],
    ),
    limit: int = _LIMIT,
    analyze_result: bool | None = _ANALYZE,
    lang: Literal["uz", "ru", "en"] = _LANG,
) -> DocumentsReport:
    """Muddati tugagan yoki tugayotgan hujjatlar — eng eskisi birinchi.

    **Beshta manba:**

    | `document_type` | Manba | Holat (26.08.2026) |
    |---|---|---|
    | `LICENSE` | `driver.license_valid_until` | 206/206 to'lgan |
    | `MEDICAL_CERTIFICATE` | `driver.medical_certificate_valid_until` | 206/206 |
    | `CREDENTIAL` | `driver_credential.expires_at` | bo'sh |
    | `VEHICLE_DOCUMENT` | `vehicle_document.expiry_date` | bo'sh |
    | `INSURANCE` | `insurance_policy.valid_to` | bo'sh |

    Bo'sh manbalar `data_quality.notes` da ochiq yoziladi — bo'sh ro'yxat
    "hujjatlar joyida" degani emas.

    **Kunlik ko'riklar bu ro'yxatga ATAYLAB kirmaydi.**
    `medical_inspection` va `vehicle_technical_inspection` (PRE_TRIP)
    har kuni yangilanadi: bazada tekshirilganda ularning "muddati"
    `inspected_at + 1 kun` ekani aniqlandi. Ya'ni "ertaga tugaydi" —
    normal holat. Ro'yxatga qo'shilsa kuniga 200 dan ortiq qator chiqib,
    haqiqiy muammoni ko'mib tashlardi. Reysga chiqishga tayyorlikni
    `/vehicle-selection/rank` tekshiradi.

    `days_left` **manfiy** bo'lsa muddat o'tgan (`expired: true`).
    """
    try:
        report = await run_in_threadpool(
            service.documents, days=days, subject_type=subject_type,
            document_type=document_type, limit=limit, lang=lang,
        )
    except DispatcherDataError as exc:
        raise HTTPException(503, f"Bazadan o'qib bo'lmadi: {exc}")
    return DocumentsReport(**await _finish(report, "documents", analyze_result, lang))
