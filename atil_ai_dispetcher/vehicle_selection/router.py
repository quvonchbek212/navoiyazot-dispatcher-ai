"""Mashina va haydovchi tanlash endpointi.

Router `main.py` dagi yagona FastAPI ilovasiga ulanadi — bu yerda alohida
`FastAPI()` yaratilmaydi, aks holda Swagger bir nechta bo'lib ketardi.
Butun ilova HTTP Basic bilan yopiq (`security.py`), shuning uchun bu yerda
autorizatsiya qayta yozilmaydi.

BITTA ENDPOINT, O'N IKKI PARAMETR. Har biri bazadagi aniq bir narsaga
tayanadi — "har ehtimolga qarshi" qo'yilgani yo'q. Chiqarib tashlanganlar
va sabablari:

    transport_request_id   `transport_request` da tanlash uchun ma'lumot yo'q:
                           25 so'rovning hammasida manzil "Navoiyazot" ->
                           "Navoiyazot", yuk ustunlari 0/36
    origin_lat/lon         o'rniga `origin_location_id` — dispetcher
                           koordinata emas, joy tanlaydi
    window_from/to         `driver_shift` da 206 haydovchidan 2 tasida yozuv
                           bor, ya'ni soatlik aniqlikni baza ko'tarmaydi.
                           Marshrut berilsa oyna undan olinadi
    branch_id/department_id  filtr sifatida so'ralmadi
    include_blocked        kutubxonada qoldi (`ranker.rank`), endpointda yo'q
"""

from __future__ import annotations

import logging
from datetime import date
from typing import Literal

from fastapi import APIRouter, HTTPException, Query
from fastapi.concurrency import run_in_threadpool

from atil_ai_dispetcher.vehicle_selection import config, ranker, texts
from atil_ai_dispetcher.vehicle_selection.explain import AnalysisUnavailable, analyze
from atil_ai_dispetcher.vehicle_selection.models import SelectionReport
from atil_ai_dispetcher.vehicle_selection.queries import SelectionDataError
from atil_ai_dispetcher.vehicle_selection.ranker import DemandNotFound

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/vehicle-selection", tags=["Mashina/haydovchi tanlash"])


@router.get(
    "/rank",
    response_model=SelectionReport,
    summary="Reysga eng mos mashina+haydovchi juftliklari",
    responses={
        400: {"description": "Transport turi berilmagan"},
        404: {"description": "Marshrut topilmadi"},
        503: {"description": "Tahlilni LLM yozib bera olmadi yoki bazaga ulanib bo'lmadi — vaqtinchalik holat, qayta urinish mumkin"},
    },
)
async def rank_pairs(
    # --------------------------------------------------------- Nima kerak
    transport_type: str | None = Query(
        None,
        description="**Talab qilinadigan transport turi.** Kod ham, NOM ham "
                    "yoziladi: `PASSENGER_CAR`, `yengil avtomobil`, "
                    "`легковой автомобиль`, `passenger car` — to'rttasi ham "
                    "bir xil ishlaydi (javobda tur NOM bo'lib chiqadi, "
                    "shuning uchun uni filtrga qaytarib yozish tabiiy). "
                    "Bazada 17 tur ishlatilyapti. "
                    "`route_id` berilmasa MAJBURIY. Bugungi baza bilan bu "
                    "amalda ishlaydigan yagona filtr: sig'im ustunlari "
                    "(`payload_capacity_kg`, `volume_m3`, `seat_count`) 0/127.",
        examples=["DUMP_TRUCK"],
    ),
    driver_category: str | None = Query(
        None,
        description="Talab qilinadigan guvohnoma toifasi: A, B, BE, C, CE, D, DE, E. "
                    "Transport turidan AVTOMATIK CHIQARIB BO'LMAYDI — `route` "
                    "jadvalidagi haqiqiy juftliklar barqaror emas "
                    "(`PASSENGER_CAR` -> B:17, D:7, CE:1, E:1, BE:1, A:1). "
                    "Berilmasa toifa tekshirilmaydi va malaka mezoni faqat "
                    "tajribani baholaydi.",
        examples=["C"],
    ),
    route_id: str | None = Query(
        None,
        description="Marshrut id — **bitta parametr bilan to'rttasini to'ldiradi**: "
                    "transport turi, haydovchi toifasi, reys oynasi va masofa. "
                    "`route` da bu ustunlar 56/56 to'ldirilgan. Berilsa "
                    "`transport_type` shart emas.",
    ),
    # -------------------------------------------------- Nima tashiladi
    cargo_weight_kg: float | None = Query(
        None, ge=0,
        description="Yuk og'irligi, kg. **Sig'im mezoni shusiz baholanmaydi.** "
                    "DIQQAT: bugun mashinalarning `payload_capacity_kg` i 0/127 "
                    "to'ldirilgan, shuning uchun bu qiymat hozircha solishtirilmaydi — "
                    "faqat javobda va LLM tahlilida ko'rinadi.",
    ),
    cargo_volume_m3: float | None = Query(
        None, ge=0, description="Yuk hajmi, m3. Sig'imning hajm tomoni (`volume_m3`)."),
    passengers: int | None = Query(
        None, ge=0,
        description="Yo'lovchi soni — avtobus va mikroavtobus uchun (`seat_count`). "
                    "Yuk emas, odam tashilayotganini shu ko'rsatadi.",
    ),
    # ------------------------------------------------------------ Qayerdan/qayerga
    origin_location_id: str | None = Query(
        None,
        description="**Qayerdan** — manzil id. `route_point` dan yechiladi "
                    "(44 ta manzil: `Цех №014`, `Склад готовой продукции` …). "
                    "Koordinatasi bo'lsa masofa mezoniga boradi.",
    ),
    destination_location_id: str | None = Query(
        None,
        description="**Qayerga** — manzil id, xuddi shu katalogdan. "
                    "DIQQAT: bugun reytingga TA'SIR QILMAYDI, javobda yozib "
                    "qo'yiladi. Borish masofasi mashina tanlashiga ta'sir qilishi "
                    "uchun `fuel_norm` kerak, u esa bo'sh (0 yozuv).",
    ),
    # ------------------------------------------------------------------ Qachon
    on_date: date | None = Query(
        None,
        description="Jo'nash sanasi. Hujjat muddatlari, tibbiy ko'rik va bandlik "
                    "shu sanaga tekshiriladi. Berilmasa marshrut sanasidan, "
                    "u ham bo'lmasa **bugundan** olinadi.",
    ),
    # ---------------------------------------------------------------- Boshqaruv
    require_medical: bool = Query(
        True,
        description="Jo'nash kuniga `FIT` tibbiy ko'rik talab qilinsinmi. "
                    "**Eng kuchli kesuvchi**: 206 haydovchidan o'sha kunga FIT "
                    "ko'rigi bo'lgani 27 ta edi (22.08.2026). `false` qilinsa "
                    "ko'rik yo'qligi kesmaydi, lekin `UNFIT` baribir kesadi.",
    ),
    limit: int = Query(
        config.DEFAULT_LIMIT, ge=1, le=config.MAX_LIMIT,
        description="Nechta variant qaytsin"),
    lang: Literal["uz", "ru", "en"] = Query(
        "uz",
        description="**Javob tili.** Matnlarning HAMMASI shu tilda chiqadi: "
                    "mezon izohi (`criteria[].detail`), kesish sabablari "
                    "(`blockers[].text`), juftlik izohi, "
                    "`summary.criteria_skipped`, `data_quality.notes` va LLM "
                    "tahlili. Bazadagi holat kodlari ham tarjima qilinadi "
                    "(`IN_MAINTENANCE` -> \"texnik xizmatda\").\n\n"
                    "**Kodlar tarjima qilinmaydi** — `blockers[].code`, mezon "
                    "nomi, jadval va ustun nomlari uch tilda ham bir xil: "
                    "ularni dastur o'qiydi.",
    ),
) -> SelectionReport:
    """Reysga **eng mos mashina+haydovchi juftliklarini** reytinglaydi.

    **Olti mezon** (`criteria` da har biri alohida ball bilan):

    | Mezon | Nima o'lchanadi | Manba |
    |---|---|---|
    | `capacity` | yuk sig'adimi va sig'imdan qanchalik to'liq foydalaniladi | `transport_vehicle`, talab |
    | `distance` | mashina yuklash nuqtasiga qanchalik yaqin | `vehicle_telemetry_state` |
    | `documents` | hujjatlar jo'nash kuniga amal qiladimi | `vehicle_document`, `insurance_policy`, `driver` |
    | `shift` | haydovchi smenasi reys oynasini qoplaydimi | `driver_shift` |
    | `skill` | toifa mosligi, tajriba, xavfsizlik tarixi | `driver_license_category`, `trip`, `incident` |
    | `technical` | mashina yo'lga yaroqlimi | `vehicle_technical_inspection`, `vehicle_repair`, `maintenance_plan` |

    **`score` `null` bo'lishi NOL EMAS.** `null` — "baholanmadi" (ma'lumot
    yo'q), nol — "baholandi va yomon". Baholanmagan mezon reytingdan
    chiqariladi va **og'irligi qolgan mezonlarga qayta taqsimlanadi**, ya'ni
    sig'imi noma'lum mashina jazolanmaydi. Qaysi mezon nima uchun tushib
    qolgani `summary.criteria_skipped` da ochiq yoziladi.

    **"Bo'sh" bayroqdan olinmaydi.** `transport_vehicle.current_status` va
    `driver.driver_availability_status` bazada yangilanmayotgani aniqlangan
    (22.08.2026: aktiv reysdagi 10 haydovchining 10 tasi ham hali
    `AVAILABLE` edi). Shuning uchun bandlik `trip` va `waybill` dan olinadi —
    ikkalasining birlashmasi bilan.

    **Kesish va ball — ikki xil narsa.** Guvohnoma muddati o'tgani, toifa mos
    kelmagani, bloklovchi remont va bandlik — bular ball emas, **kesish**:
    variant ro'yxatga umuman tushmaydi va `summary.blocker_counts` da
    nechtasini kesgani ko'rinadi.

    **Tanlash arifmetika bilan, tahlil LLM bilan.** Ballarni hisob quradi —
    shuning uchun bir xil so'rovga bir xil tartib chiqadi va har bir ball
    `criteria[...].detail` orqali qo'lda tekshiriladi. LLM esa yuqori
    variantlarni **birgalikda** ko'rib chiqadi: taqqoslaydi, xavfni
    ko'rsatadi va tavsiya beradi (`analysis`). **Tahlil shablonga
    tushmaydi**: LLM javob bermasa endpoint 503 qaytaradi, chunki yarim
    javob "AI tahlil qildi" degan yolg'on taassurot berardi.

    **Bazaga ta'sir:** faqat `SELECT`, READ ONLY tranzaksiyada.
    """
    if not (route_id or transport_type):
        raise HTTPException(
            400, "`transport_type` yoki `route_id` dan biri berilishi kerak"
        )

    try:
        result = await run_in_threadpool(
            ranker.rank,
            route_id=route_id,
            transport_type=transport_type,
            driver_category=driver_category,
            cargo_weight_kg=cargo_weight_kg,
            cargo_volume_m3=cargo_volume_m3,
            passengers=passengers,
            origin_location_id=origin_location_id,
            destination_location_id=destination_location_id,
            on_date=on_date,
            require_medical=require_medical,
            limit=limit,
            lang=lang,
        )
    except DemandNotFound as exc:
        raise HTTPException(404, str(exc))
    except SelectionDataError as exc:
        # Baza yotgan bo'lsa 500 emas, 503: bu vaqtinchalik holat va
        # chaqiruvchi qayta urinishi mumkin.
        raise HTTPException(503, f"Bazadan o'qib bo'lmadi: {exc}")

    # TAHLIL DOIM YOZILADI va u FAQAT LLM dan keladi. Shablonga tushish
    # yo'q: LLM javob bermasa 503 qaytadi va frontend "keyinroq urinib
    # ko'ring" deydi. Yarim javob ko'rsatishdan ko'ra ochiq xato ma'qul.
    try:
        await analyze(result, lang=lang)
    except AnalysisUnavailable as exc:
        raise HTTPException(503, str(exc))

    return SelectionReport(**result)
