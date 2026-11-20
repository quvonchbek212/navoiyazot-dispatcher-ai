"""Bazadan o'qish — FAQAT SELECT.

BU FAYLDA BITTA SO'ROV BOR va u ataylab shunday. Agent hisob-kitobni
takrorlamaydi: kechikish, og'ish, bekor turish va hujjat muddati
`dispatcher_assistant` da, reja esa `Marshrut_optimizatsiyasi` da
hisoblanadi. Agent ularni chaqiradi.

Bu yerdagi yagona so'rov esa hech qayerda yo'q: "ariza QANCHA VAQTDAN
BERI kutayapti". `Marshrut_optimizatsiyasi` arizani reja uchun o'qiydi
va kutish vaqtini qaytarmaydi — unga kerak emas. Agentga esa aynan shu
kerak, chunki uning ishi navbatni ko'rsatish.

KUTISH VAQTI — MEYOR EMAS, AYIRMA. "Necha soatdan keyin ariza kech
qolgan hisoblanadi" degan raqam bu yerda ham, `config.py` da ham yo'q.
Faqat ikkita SOLISHTIRISH bor:
    waiting_hours    hozir - `created_at`   (qancha kutdi)
    overdue_minutes  hozir - `planned_departure_at`, faqat u O'TGAN
                     bo'lsa (rejadagi jo'nash vaqti kelib bo'ldi,
                     ariza esa hali mashinaga berilmagan)
Ikkalasi ham sanani sana bilan solishtirish.

VAQT TIPLARI ARALASH — `dispatcher_assistant/queries.py` dagi bilan
bir xil muammo. `transport_request.created_at` — `timestamptz`,
`planned_departure_at` — zonasiz `timestamp`. Shuning uchun "hozir"
so'rovga PARAMETR bo'lib boradi va har biri o'z tipiga keltiriladi.
"""

from __future__ import annotations

import logging
import re
import sys
from datetime import datetime
from pathlib import Path
from typing import Any, Sequence

_CHATBOT_DIR = Path(__file__).resolve().parents[2] / "atil_chatbot"
if str(_CHATBOT_DIR) not in sys.path:
    sys.path.insert(0, str(_CHATBOT_DIR))

import psycopg2  # noqa: E402
import psycopg2.sql  # noqa: E402

from db.connect_db_for_server import read_only_cursor  # noqa: E402

logger = logging.getLogger(__name__)

#: Ariza navbati qaysi jadvallarga tayanadi — `data_quality.row_counts` uchun.
SOURCE_TABLES = ("transport_request", "transport_request_point", "transport_vehicle", "route")

#: Jadval nomlari faqat SHU modulning konstantalaridan keladi, hech
#: qachon so'rovdan emas. Shunga qaramay nom tekshiriladi: keyin kimdir
#: bu funksiyalarga tashqaridan nom uzatsa, u yerda emas, SHU YERDA
#: to'xtasin.
_SAFE_NAME = re.compile(r"^[a-z_][a-z0-9_]*$")


class AgentDataError(RuntimeError):
    """Bazadan o'qib bo'lmadi — router buni 503 ga aylantiradi."""


WAITING_SQL = """
select
    r.id::text                   as request_id,
    r.request_number,
    r.status,
    r.priority,
    r.request_type,
    r.waybill_category,
    r.required_transport_type,
    r.cargo_description,
    r.purpose,
    r.department_name,
    r.from_branch_name,
    r.to_branch_name,
    r.origin_location,
    r.destination_location,
    r.initiator_name,
    r.created_at,
    coalesce((nullif(to_jsonb(r)->>'planning_start_instant','')::timestamptz AT TIME ZONE 'Asia/Tashkent'),r.planned_departure_at) as planned_departure_at,
    coalesce((nullif(to_jsonb(r)->>'planning_end_instant','')::timestamptz AT TIME ZONE 'Asia/Tashkent'),r.planned_arrival_at) as planned_arrival_at,
    extract(epoch from (%s::timestamptz - r.created_at)) / 3600.0 as waiting_hours,
    case
        when coalesce((nullif(to_jsonb(r)->>'planning_start_instant','')::timestamptz AT TIME ZONE 'Asia/Tashkent'),r.planned_departure_at) is not null
             and coalesce((nullif(to_jsonb(r)->>'planning_start_instant','')::timestamptz AT TIME ZONE 'Asia/Tashkent'),r.planned_departure_at) < %s::timestamp
        then extract(epoch from (%s::timestamp - coalesce((nullif(to_jsonb(r)->>'planning_start_instant','')::timestamptz AT TIME ZONE 'Asia/Tashkent'),r.planned_departure_at))) / 60.0
    end                          as overdue_minutes
from transport_request r
where r.status = any(%s::text[])
order by r.created_at
limit %s
"""


def fetch_waiting(
    *,
    now: datetime,
    statuses: Sequence[str],
    limit: int,
) -> list[dict[str, Any]]:
    """Rejalashtirishni kutayotgan arizalar — eng eskisi birinchi.

    Tartib SQL da `created_at` bo'yicha: `limit` ga yetilganda kesilib
    qoladigani eng YANGISI bo'lsin. Muhimlik bo'yicha qayta saralash
    Python da (`backlog.py`) — u yerda `Marshrut_optimizatsiyasi` dagi
    `PRIORITY_ORDER` ishlatiladi va tartib ikki joyda ikki xil
    ta'riflanmaydi.

    `statuses` bo'sh bo'lsa bazaga BORILMAYDI: `any('{}')` hech narsa
    qaytarmaydi, ya'ni bo'sh ro'yxat "kutayotgan ariza yo'q" bo'lib
    ko'rinardi — aslida sozlama to'ldirilmagan bo'lardi.
    """
    if not statuses:
        raise AgentDataError(
            "Ariza holatlari sozlanmagan (`RO_REQUEST_STATUSES` bo'sh) — "
            "navbatni aniqlab bo'lmaydi"
        )
    naive = now.replace(tzinfo=None)
    return _select(
        WAITING_SQL,
        (now, naive, naive, [str(s) for s in statuses], int(limit)),
    )


def has_rows(tables: Sequence[str]) -> dict[str, bool]:
    """Jadvalda ma'lumot BORMI — statistika emas, haqiqiy so'rov.

    NIMA UCHUN `pg_stat_user_tables` ISHLATILMAYDI. Boshqa modullarda
    `data_quality.row_counts` shu statistikadan olinadi va u BU BAZADA
    YOLG'ON GAPIRADI (03.09.2026 da tekshirilgan):

        jadval             n_live_tup    haqiqiy count(*)
        driver                      0                 206
        transport_vehicle           0                 128
        trip                       17                 199

    Sabab: `n_live_tup` — `ANALYZE` dan keyin yangilanadigan TAXMIN,
    va bu bazada u yangilanmagan. Agent uchun bu jimgina falokat
    bo'lardi: u "`driver` jadvali bo'sh, hujjatlar tekshirilmayapti"
    deb xabar berardi — aslida 412 ta hujjat tekshirilgan holda.

    `exists` esa birinchi qatorni topishi bilan to'xtaydi: katta
    jadvalda ham arzon va, eng muhimi, ROST.
    """
    names = [t for t in tables if _SAFE_NAME.match(t)]
    if not names:
        return {}
    query = psycopg2.sql.SQL(" union all ").join(
        psycopg2.sql.SQL(
            "select {label} as table_name, exists(select 1 from {ident}) as has_rows"
        ).format(label=psycopg2.sql.Literal(name), ident=psycopg2.sql.Identifier(name))
        for name in names
    )
    rows = _select(query)
    return {row["table_name"]: bool(row["has_rows"]) for row in rows}


def table_counts(tables: Sequence[str]) -> dict[str, int]:
    """Aniq `count(*)`.

    Faqat SHU modulning kichik manba jadvallariga qo'llanadi
    (`SOURCE_TABLES` — 03.09.2026 da eng kattasi 230 qator) va soatiga
    bir marta chaqiriladi. Katta jadvalga `count(*)` yozish qimmat
    bo'lardi; "bormi yo'qmi" degan savolga esa yuqoridagi `has_rows`
    javob beradi.
    """
    names = [t for t in tables if _SAFE_NAME.match(t)]
    if not names:
        return {}
    query = psycopg2.sql.SQL(" union all ").join(
        psycopg2.sql.SQL("select {label} as table_name, count(*) as n from {ident}").format(
            label=psycopg2.sql.Literal(name), ident=psycopg2.sql.Identifier(name)
        )
        for name in names
    )
    return {row["table_name"]: int(row["n"] or 0) for row in _select(query)}


def _select(sql: Any, params: Sequence[Any] | None = None) -> list[dict[str, Any]]:
    try:
        with read_only_cursor() as cur:
            cur.execute(sql, tuple(params or ()))
            return [dict(row) for row in cur.fetchall()]
    except psycopg2.Error as exc:
        message = (getattr(exc, "pgerror", None) or str(exc)).strip().splitlines()[0]
        logger.warning("Agent so'rovi bajarilmadi: %s", message[:300])
        raise AgentDataError(message[:300]) from exc
    except Exception as exc:  # noqa: BLE001
        logger.exception("Bazaga ulanishda kutilmagan xato")
        raise AgentDataError(f"{type(exc).__name__}: {exc}"[:300]) from exc
