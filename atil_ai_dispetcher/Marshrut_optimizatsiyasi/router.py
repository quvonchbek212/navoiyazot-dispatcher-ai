"""Marshrut optimizatsiyasi endpointi.

Router `main.py` dagi yagona FastAPI ilovasiga ulanadi — bu yerda alohida
`FastAPI()` yaratilmaydi, aks holda Swagger bir nechta bo'lib ketardi.
Butun ilova HTTP Basic bilan yopiq (`security.py`), shuning uchun bu yerda
autorizatsiya qayta yozilmaydi.

BITTA ENDPOINT, IKKI REJIM. Rejimni alohida bayroq emas, `stops` maydoni
belgilaydi:

    {}                      -> bazadagi arizalar bo'yicha reja
    {"stops": [...], ...}   -> berilgan nuqtalar bo'yicha, bazaga tegilmaydi

NIMA UCHUN POST, GET EMAS: nuqtalar ro'yxatini query-string'ga sig'dirib
bo'lmaydi. Ikkinchi rejim uchun alohida endpoint ochish esa bir xil
javob qaytaradigan ikki yo'l demakdi — foydalanuvchi qaysi birini
tanlashini o'ylab o'tirardi.

TANASI TO'LIQ IXTIYORIY: `{}` yuborilsa ham ishlaydi (bugungi arizalar,
`.env` dagi sukut sozlamalar bilan).

PARAMETRLAR QISQA QILIB TANLANGAN — har biri bazadagi aniq bir narsaga
tayanadi. Chiqarib tashlanganlar `optimizer.plan_from_database()` da
KUTUBXONA sifatida qoldi (vehicle_selection dagi `include_blocked` kabi),
sabablari bilan:

    status              `.env` dagi `RO_REQUEST_STATUSES` yetarli, so'rovda
                        o'zgartirish ehtiyoji chiqmadi
    vehicle_id          park kichik, filtr kerak emas
    depot_location_id   garaj endi mashinaning O'Z FILIALIDAN olinadi
                        (`reference_data`, BRANCHES), ya'ni id so'rashning
                        keragi yo'q
    service_minutes     `.env` dagi `RO_FALLBACK_SERVICE_MINUTES`
    respect_capacity    sig'im to'lganda qattiq bo'lishi to'g'ri — tugma
                        qilib qo'yish uni tasodifan o'chirib qo'yishga
                        yo'l ochardi

BUTUNLAY OLIB TASHLANGAN: `hazard_un_number`. Xavflilik endi so'rovda
emas, BAZADAN avtomatik aniqlanadi:
`transport_request.wms_shipment_id` -> `shipment.hazard_profile_id` ->
`hazard_profile.requires_special_tank`. Sabab: xavflilik butun so'rovga
emas, AYRIM ARIZAGA tegishli xususiyat — bir kunda ham xavfli, ham oddiy
yuk bo'ladi. Uni odam qo'lda kiritishi esa xato manbai bo'lardi.
"""

from __future__ import annotations

import logging
from typing import Literal

from fastapi import APIRouter, Body, HTTPException, Query
from fastapi.concurrency import run_in_threadpool

from atil_ai_dispetcher.Marshrut_optimizatsiyasi import optimizer, texts
from atil_ai_dispetcher.Marshrut_optimizatsiyasi.explain import (
    AnalysisUnavailable, analyze, fill_templates,
)
from atil_ai_dispetcher.Marshrut_optimizatsiyasi.models import PlanRequest, RoutePlanReport
from atil_ai_dispetcher.Marshrut_optimizatsiyasi.optimizer import NothingToPlan
from atil_ai_dispetcher.Marshrut_optimizatsiyasi.queries import PlanningDataError

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/route-optimization", tags=["Marshrut optimizatsiyasi"])

EXAMPLES = {
    "bugungi_arizalar": {
        "summary": "Bugungi arizalar",
        "description":
            "Bazadagi bugungi arizalarni o'qiydi va holatni ko'rsatadi. "
            "Hech qanday maydon shart emas — sana bugun, holatlar, maqsad va "
            "vaqt byudjeti `.env` dan olinadi.\n\n"
            "Tahlilni har doim LLM yozadi — u rejaning O'ZIGA tegmaydi "
            "(bir xil so'rovga bir xil reja chiqaveradi), faqat o'zbekcha "
            "izoh qo'shadi va javobni ~10 soniyaga cho'zadi. LLM javob "
            "bermasa endpoint 503 qaytaradi.\n\n"
            "Bu namuna \"bugun nima bor\" degan savol uchun: nechta ariza "
            "kutayapti, nechta mashina bo'sh, kalibrovka nimani o'lchay oldi.\n\n"
            "Reja chiqmasligi mumkin — u holda `data_quality.requirements` "
            "nima yetishmayotganini aytadi.",
        "value": {},
    },
    "taqsimlash": {
        "summary": "Arizalarni taqsimlash",
        "description":
            "Asosiy ish: arizalarni mashinalarga taqsimlab, borish tartibini "
            "tuzadi. Bazadagi `transport_request`, `transport_vehicle`, "
            "`trip`, `waybill`, `route_point`, `trip_event` va `reference_data` "
            "jadvallaridan foydalanadi.\n\n"
            "**Hech qanday maydon berilmaydi.** Reja uchun kerak bo'lgan "
            "hamma narsa — arizalar, mashinalar, ularning turgan joyi, "
            "o'rtacha tezlik, yuklash vaqti — BAZADAN olinadi. So'rovdagi "
            "maydonlar faqat bazani BEKOR QILISH uchun: ular yozilgan "
            "raqam o'lchangan raqamdan ustun turadi.\n\n"
            "**Ma'lumot yetmasa javob yo'naltiradi.** `data_quality.ready` "
            "bazadan reja tuzsa bo'ladimi degan savolga javob beradi, "
            "`data_quality.requirements` esa har bir talab uchun QAYSI JADVAL "
            "va QAYSI USTUN kerakligini, u yerda hozir nechta yaroqli qator "
            "borligini va to'lmasa rejaga nima bo'lishini ko'rsatadi. "
            "Bloklovchi talablar (`blocking: true`) ro'yxatning boshida "
            "turadi.\n\n"
            "**Bugun reja chiqmasligi kutilgan holat.** Bazada arizalarning "
            "koordinatasi ham, mashinalarning turgan joyi ham hali yo'q. "
            "Ma'lumot kiritilgan sari `ready` o'zi `true` ga aylanadi va "
            "reja o'zi chiqa boshlaydi — KOD O'ZGARMAYDI.",
        "value": {},
    },
}


@router.post(
    "/plan",
    response_model=RoutePlanReport,
    summary="Arizalarni mashinalarga taqsimlab, marshrut tuzish",
    responses={
        404: {"description": "Rejalashtiriladigan ariza topilmadi — javobda "
                             "bazaning tayyorlik holati (`requirements`) ham keladi"},
        503: {"description": "Tahlilni LLM yozib bera olmadi yoki bazaga ulanib bo'lmadi — vaqtinchalik holat, qayta urinish mumkin"},
    },
)
async def plan(
    lang: Literal["uz", "ru", "en"] = Query(
        "uz",
        description="**Javob tili.** Matnlarning HAMMASI shu tilda chiqadi: "
                    "joylanmagan arizaning sababi va muhimligi, transport "
                    "turining nomi (`AERIAL_PLATFORM` -> \"havo platformasi\" "
                    "/ \"\u0430\u0432\u0442\u043e\u0432\u044b\u0448\u043a\u0430\" / \"aerial platform\"), "
                    "`data_quality.notes`, `requirements` dagi tushuntirish, "
                    "marshrut izohi va LLM tahlili.\n\n"
                    "**Kodlar tarjima qilinmaydi** \u2014 `reason_code`, `need`, "
                    "`kind`, jadval va ustun nomlari uch tilda ham bir xil "
                    "qoladi: ularni dastur o'qiydi va til o'zgarganda "
                    "chaqiruvchining filtri buzilmasligi kerak.",
    ),
    payload: PlanRequest = Body(default_factory=PlanRequest, openapi_examples=EXAMPLES),
) -> RoutePlanReport:
    """Arizalarni mashinalarga taqsimlaydi va **borish tartibini** tuzadi.

    **Masala:** har bir ariza — A nuqtadan B nuqtaga yuk. Bir mashina bir
    necha arizani ketma-ket bajarishi mumkin, lekin yuk avval **olinishi**,
    keyin **tushirilishi** kerak va sig'imdan oshmasligi shart. Bu klassik
    PDPTW masalasi.

    **Ikki rejim, bitta endpoint.** `stops` berilmasa arizalar bazadan
    (`transport_request`) o'qiladi; berilsa bazaga umuman murojaat
    qilinmaydi. Javob ikkalasida ham bir xil.

    **Qanday yechiladi (`solver.py`):**

    | Bosqich | Nima qiladi |
    |---|---|
    | Qurish | har arizani eng arzon joyga qo'yadi (barcha mashina, barcha o'rin) |
    | Ko'chirish | arizani boshqa mashinaga o'tkazib ko'radi |
    | Almashtirish | ikki mashinadagi ikki arizani almashtiradi |

    Har bir yurish faqat **narxni kamaytirsa** qabul qilinadi, tasodifiy son
    ishlatilmaydi — ya'ni bir xil so'rovga **bir xil reja** chiqadi.

    **Bazadagi qarorlar hurmat qilinadi.** Dispetcher arizani qo'lda
    biriktirgan bo'lsa (`transport_request.binding_vehicle_id`), optimizator
    uni **boshqa mashinaga ko'chirmaydi** — qolgan rejani shu qaror
    atrofida quradi. Xavfli yuk `shipment` -> `hazard_profile` zanjiridan
    **avtomatik** aniqlanadi: sisterna talab qilinsa faqat `TANKER` va
    `WATER_TRUCK` ko'rib chiqiladi.

    **Bandlik vaqt bo'yicha hisoblanadi.** "Aktiv reysi bor" degani band
    degani emas: ertalab 11:00 da reysini tugatadigan mashina tushdan
    keyingi marshrutga yaroqli. `window_from`/`window_to` bilan kunning
    bir qismiga qayta reja tuzish mumkin.

    **Raqamlar o'ylab topilmaydi.** Yo'l koeffitsienti, o'rtacha tezlik va
    yuklash vaqti bazadan **o'lchanadi** (`route_point`, `trip`,
    `trip_event`). O'lchov yetmasa qiymat **noma'lum** bo'lib qoladi va
    nolga aylanmaydi: tezlik noma'lum bo'lsa vaqt oynasi tekshirilmaydi va
    bu `calibration.time_aware=false` bilan ochiq ko'rsatiladi.

    **Joylanmagan ariza yo'qolmaydi.** Har biri `unassigned` da sababi
    bilan qaytadi: koordinata yo'q, mos mashina yo'q, sig'im yetmadi,
    vaqtga ulgurmaydi, smena chegarasi.

    **Foyda o'lchanadi.** `summary.baseline_distance_km` — har arizani
    alohida mashinada tashiganda chiqadigan masofa (dispetcher qo'lda
    ishlaganda amalda shunday bo'ladi). `saved_percent` — reja shunga
    nisbatan qancha qisqartirgani.

    **Javob tili — `lang`.** `uz` (sukut), `ru`, `en`. Butun javob shu
    tilda chiqadi: joylanmagan ariza sababi, transport turining nomi
    (`AERIAL_PLATFORM` -> "havo platformasi" / "автовышка" / "aerial
    platform"), `data_quality.notes`, `requirements` va LLM tahlili.

    **Kodlar tarjima qilinmaydi** — `reason_code`, `need`, `kind`, jadval
    va ustun nomlari uch tilda ham bir xil qoladi: ularni dastur o'qiydi
    va til o'zgarganda chaqiruvchining filtri buzilmasligi kerak.

    **Ma'lumot yetmasa javob YO'NALTIRADI.** `data_quality.ready` — bazadan
    reja tuzsa bo'ladimi. `data_quality.requirements` — har bir talab uchun
    qaysi jadval, qaysi ustun kerakligi, u yerda hozir nechta yaroqli qator
    borligi (`usable_rows`) va to'lmasa rejaga nima bo'lishi (`impact`).
    Bloklovchilari (`blocking: true`) ro'yxat boshida turadi.

    | Talab | Jadval | Busiz nima bo'ladi |
    |---|---|---|
    | Ariza | `transport_request` | reja tuzilmaydi (404) |
    | Koordinata | `transport_request_point` -> `transport_request` -> `reference_data` | ariza `NO_COORDINATES` |
    | Mashina | `transport_vehicle` | ariza `NO_VEHICLE_LEFT` |
    | Chiqish nuqtasi | `vehicle_telemetry_state` -> `reference_data` (BRANCHES) -> so'rovdagi garaj | mashina rejaga kirmaydi |
    | Tezlik | `trip` -> `route_point` | vaqt hisoblanmaydi |
    | Sig'im | `transport_vehicle` + `transport_request` | sig'im tekshirilmaydi |

    `row_counts` — jadvallardagi **haqiqiy** qator soni (`count(*)`), butun
    tayyorlik holati bilan birga bitta so'rovda olinadi.

    **Bazaga ta'sir:** faqat `SELECT`, READ ONLY tranzaksiyada.
    """
    lang = texts.normalize(lang)
    # Til so'rov tanasida emas, query'da keladi; quyi qatlamlar esa bitta
    # lug'atdan o'qiydi, shuning uchun shu yerda qo'shib yuboriladi.
    body = payload.model_dump()
    body["lang"] = lang
    try:
        result = await run_in_threadpool(optimizer.plan, body)
    except NothingToPlan as exc:
        # 404 quruq matn bo'lib qolmaydi. "Ariza topilmadi" deganda darrov
        # "nega?" degan savol tug'iladi va javob `transport_request` da
        # nechta qator borligi va qaysi holat kutilayotganida — shuning
        # uchun tayyorlik holati xato tanasiga ham qo'shiladi.
        raise HTTPException(404, {"message": exc.message, **exc.report})
    except PlanningDataError as exc:
        # Baza yotgan bo'lsa 500 emas, 503: bu vaqtinchalik holat va
        # chaqiruvchi qayta urinishi mumkin.
        raise HTTPException(
            503, texts.t(lang, "error.db", error=exc))

    fill_templates(result, lang)

    # TAHLIL DOIM YOZILADI va u FAQAT LLM dan keladi. Shablonga tushish
    # yo'q: LLM javob bermasa 503 qaytadi va frontend "keyinroq urinib
    # ko'ring" deydi. Yarim javob ko'rsatishdan ko'ra ochiq xato ma'qul.
    try:
        await analyze(result, lang=lang)
    except AnalysisUnavailable as exc:
        raise HTTPException(503, str(exc))

    return RoutePlanReport(**result)
