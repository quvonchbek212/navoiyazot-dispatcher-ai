"""Agent xabarlarining matni — uch tilda (uz, ru, en).

BU MODULDA TIL BOSHQACHA ISHLAYDI. Qolgan uch modul javobni so'rov
paytida hisoblaydi, shuning uchun ularda `?lang=` to'g'ridan-to'g'ri
matnni tanlaydi. Agent esa xabarni SIKL paytida (har 15 daqiqada)
tuzadi va faylga yozib qo'yadi — o'qish paytida esa u allaqachon
yozilgan bo'ladi.

Shuning uchun agent matnni EMAS, KALIT + PARAMETR ni saqlaydi:

    {"key": "queue.new.title", "params": {"count": 3}}

`GET /agent/notifications?lang=ru` chaqirilganda xabar SHU YERDA,
o'qish paytida quriladi. Natijada bitta yozuv har bir foydalanuvchiga
o'z tilida ko'rinadi va fayl uch barobar o'smaydi.

MATNSIZ QOLGAN JOYLAR. Ikki narsani qayta qurib bo'lmaydi:

  * LLM yozgan xulosa — u sikl paytida yoziladi. Shuning uchun u
    UCHALA TILDA yoziladi va uchalasi saqlanadi (`responder.py`).
  * boshqa moduldan kelgan izohlar (`data_quality.notes`) — ular xom
    matn bo'lib keladi. Ular qanday kelgan bo'lsa shunday saqlanadi va
    ko'rsatiladi.

KODLAR TARJIMA QILINMAYDI. `agent`, `kind`, `event_type`, `severity`,
`entity_type`, `dedupe_key`, `action_url` — bular mashina o'qiydigan
qiymatlar va uch tilda ham bir xil qoladi.
"""

from __future__ import annotations

import sys
from pathlib import Path
from typing import Any

# `core.lang` atil_chatbot ichida yassi nom bilan import qiladi.
_CHATBOT_DIR = Path(__file__).resolve().parents[2] / "atil_chatbot"
if str(_CHATBOT_DIR) not in sys.path:
    sys.path.insert(0, str(_CHATBOT_DIR))

from core.lang import answer_instruction  # noqa: E402

#: Qo'llab-quvvatlanadigan tillar — boshqa modullar bilan bir xil.
LANGS = ("uz", "ru", "en")
DEFAULT_LANG = "uz"


def normalize(lang: str | None) -> str:
    """Noma'lum yoki bo'sh til sukut tilga tushadi."""
    value = (lang or "").strip().lower()
    return value if value in LANGS else DEFAULT_LANG


def llm_instruction(lang: str) -> str:
    """LLM promptiga qo'shiladigan til ko'rsatmasi — chatbotnikidan."""
    return answer_instruction(normalize(lang))


def t(lang: str, key: str, **kwargs: Any) -> str:
    """Kalitni tanlangan tilda qaytaradi.

    Kalit topilmasa KALITNING O'ZI qaytadi — javob bo'sh qolmaydi va
    yetishmayotgan matn darrov ko'zga tashlanadi.
    """
    row = MESSAGES.get(key)
    if row is None:
        return key
    text = row.get(normalize(lang)) or row[DEFAULT_LANG]
    return text.format(**kwargs) if kwargs else text


# ------------------------------------------------------------- Spetsifikatsiya
#
# Saqlanadigan matn ikki xil bo'ladi:
#   {"key": "...", "params": {...}}   -> tarjima qilinadi
#   {"text": "..."}                   -> qanday bo'lsa shunday (boshqa
#                                        moduldan kelgan xom izoh)


def spec(key: str, **params: Any) -> dict[str, Any]:
    """Tarjima qilinadigan matn spetsifikatsiyasi."""
    return {"key": key, "params": params}


def literal(text: str) -> dict[str, Any]:
    """Tarjima qilinmaydigan xom matn (boshqa moduldan kelgan izoh)."""
    return {"text": text}


def by_lang(rows: dict[str, str]) -> dict[str, Any]:
    """Model yozgan matn — har til uchun alohida.

    Kalit bilan quriladigan matndan farqi: uni qayta tarjima qilib
    bo'lmaydi, shuning uchun sikl paytida uchala tilda yozilgan.
    """
    return {"by_lang": dict(rows)}


def _is_spec(value: Any) -> bool:
    return isinstance(value, dict) and (
        "key" in value or "text" in value or "by_lang" in value
    )


def render(item: Any, lang: str) -> str:
    """Bitta spetsifikatsiyani matnga aylantiradi.

    Eski yozuvlar (kalitsiz, tayyor matn bilan) ham o'tadi — ular
    qanday saqlangan bo'lsa shunday qaytadi. Shu tufayli tilni
    qo'shish faylni buzmaydi.
    """
    if item is None:
        return ""
    if isinstance(item, str):
        return item
    if isinstance(item, dict):
        if item.get("key") == "plan.requirement":
            return _requirement((item.get("params") or {}).get("need"), lang)
        if "by_lang" in item:
            # Model yozgan matn: kaliti yo'q, shuning uchun sikl paytida
            # uchala tilda yozilgan. Kerakli til bo'lmasa sukut tilga
            # tushamiz — bo'sh javob ko'rsatishdan yaxshiroq.
            row = item["by_lang"] or {}
            return str(row.get(normalize(lang)) or row.get(DEFAULT_LANG) or "")
        if "key" in item:
            # Parametrning O'ZI kalit bo'lishi mumkin: sarlavha
            # "{list} — TEKSHIRILMAYAPTI" bo'lsa, `list` ham tarjima
            # qilinishi kerak. Aks holda ruscha sarlavha ichida
            # o'zbekcha ro'yxat nomi turardi.
            params = {
                name: _param(value, lang)
                for name, value in (item.get("params") or {}).items()
            }
            return t(lang, item["key"], **params)
        return str(item.get("text") or "")
    return str(item)


def _requirement(need: str | None, lang: str) -> str:
    """Marshrut modulidagi talabning nomi va ta'siri.

    Reja tuzilmaganda agent "nima to'ldirilsin" deb yozadi, matn esa
    MARSHRUT modulida uch tilda turibdi. Uni ko'chirib olmaymiz — sikl
    paytida faqat talab KODI saqlanadi va o'qish paytida o'sha modulning
    o'z lug'atidan ochiladi. Shu tufayli matn ikki joyda ikki xil
    bo'lib qolmaydi.
    """
    if not need:
        return ""
    try:
        from atil_ai_dispetcher.Marshrut_optimizatsiyasi import texts as ro_texts
        from atil_ai_dispetcher.Marshrut_optimizatsiyasi.readiness import _TEXT_KEY
    except Exception:  # pragma: no cover — modul bo'lmasa kod qaytadi
        return str(need)
    key = _TEXT_KEY.get(need)
    if not key:
        return str(need)
    title = ro_texts.t(lang, f"req.{key}.title")
    # `impact` parametrsiz — shuning uchun aynan u olinadi; `hint` da
    # o'rin to'ldiruvchilar bor va ular sikl paytida ma'lum emas.
    impact = ro_texts.t(lang, f"req.{key}.impact")
    return f"{title} — {impact}".strip(" —")


def _param(value: Any, lang: str) -> Any:
    """Bitta parametrni matnga aylantiradi.

    RO'YXAT — qatorning DUMI: bo'laklar `·` bilan qo'shiladi va bo'sh
    bo'lsa hech narsa qo'shilmaydi. Shu tufayli shablon oddiy
    `"{who} — {duration}{tail}"` bo'lib qolaveradi va har bir agent
    o'zi ajratgich yozib o'tirmaydi.
    """
    if isinstance(value, (list, tuple)):
        parts = [p for p in (render(v, lang) for v in value) if p]
        return (" · " + " · ".join(parts)) if parts else ""
    if _is_spec(value):
        return render(value, lang)
    return value


def render_all(items: Any, lang: str) -> list[str]:
    """Spetsifikatsiyalar ro'yxatini matnlar ro'yxatiga aylantiradi."""
    return [render(one, lang) for one in (items or [])]


MESSAGES: dict[str, dict[str, str]] = {

    # ------------------------------------------------- Kuzatuv ro'yxatlari
    #
    # Har bir agent kuzatadigan ro'yxatning nomi. Sarlavhalarga qo'yiladi,
    # shuning uchun bosh harf bilan boshlanmaydi.
    "list.delayed": {
        "uz": "kechikayotgan reyslar",
        "ru": "опаздывающие рейсы",
        "en": "delayed trips",
    },
    "list.deviation": {
        "uz": "yo'nalishdan og'gan mashinalar",
        "ru": "машины, отклонившиеся от маршрута",
        "en": "vehicles off route",
    },
    "list.document": {
        "uz": "muddati o'tgan hujjatlar",
        "ru": "просроченные документы",
        "en": "expired documents",
    },
    "list.idle": {
        "uz": "bekor turgan mashinalar",
        "ru": "простаивающие машины",
        "en": "idle vehicles",
    },
    "list.parts": {
        "uz": "ehtiyot qism shubhalari",
        "ru": "подозрения по запчастям",
        "en": "spare-part suspicions",
    },
    "list.service": {
        "uz": "qism almashtirish vaqti",
        "ru": "сроки замены деталей",
        "en": "part replacement due",
    },

    # ------------------------------------------------- Kuzatuvchi xabarlari
    "watch.blind.title": {
        "uz": "{list} — TEKSHIRILMAYAPTI",
        "ru": "{list} — НЕ ПРОВЕРЯЮТСЯ",
        "en": "{list} — NOT BEING CHECKED",
    },
    "watch.blind.text": {
        "uz": "`{table}` jadvali bo'sh — bu ro'yxat umuman tekshirilmayapti.",
        "ru": "Таблица `{table}` пуста — этот список вообще не проверяется.",
        "en": "The `{table}` table is empty — this list is not being checked at all.",
    },
    "watch.blind.hint": {
        "uz": "Bo'sh ro'yxat \"muammo yo'q\" degani emas.",
        "ru": "Пустой список не означает «проблем нет».",
        "en": "An empty list does not mean \"no problems\".",
    },
    "watch.recovered.title": {
        "uz": "{list} — tekshiruv tiklandi",
        "ru": "{list} — проверка восстановлена",
        "en": "{list} — checking has resumed",
    },
    "watch.recovered.text": {
        "uz": "`{table}` jadvaliga ma'lumot kela boshladi, kuzatuv ishlayapti.",
        "ru": "В таблицу `{table}` пошли данные, наблюдение работает.",
        "en": "Data started arriving in `{table}`; monitoring is working.",
    },
    "watch.baseline.title": {
        "uz": "Kuzatuv boshlandi — {list}",
        "ru": "Наблюдение начато — {list}",
        "en": "Monitoring started — {list}",
    },
    "watch.baseline.text": {
        "uz": "Hozirgi holat yozib olindi: {count} ta. Bundan keyin faqat "
              "YANGI paydo bo'lgani xabar qilinadi.",
        "ru": "Текущее состояние зафиксировано: {count}. Дальше будет "
              "сообщаться только о НОВОМ.",
        "en": "The current state was recorded: {count}. From now on only NEW "
              "entries will be reported.",
    },
    "watch.new.title": {
        "uz": "{count} ta yangi — {list}",
        "ru": "{count} новых — {list}",
        "en": "{count} new — {list}",
    },
    "watch.template": {
        "uz": "{count} ta yangi qator: {list}.{top}",
        "ru": "{count} новых строк: {list}.{top}",
        "en": "{count} new row(s): {list}.{top}",
    },
    "watch.template.top": {
        "uz": " Eng ustidagisi — {line}.",
        "ru": " Самая верхняя — {line}.",
        "en": " The topmost one — {line}.",
    },
    "watch.hint.full_list": {
        "uz": "To'liq ro'yxat: {endpoint}",
        "ru": "Полный список: {endpoint}",
        "en": "Full list: {endpoint}",
    },

    # -------------------------------------------------------- Qator matnlari
    "line.delayed": {
        "uz": "{trip} — {hours} soat kechikdi ({kind}){tail}",
        "ru": "{trip} — опоздание {hours} ч ({kind}){tail}",
        "en": "{trip} — {hours} h late ({kind}){tail}",
    },
    "delay.not_departed": {
        "uz": "jo'namagan", "ru": "не выехал", "en": "not departed"},
    "delay.en_route": {"uz": "yo'lda", "ru": "в пути", "en": "en route"},

    "line.deviation": {
        "uz": "{who} — {distance}{tail}", "ru": "{who} — {distance}{tail}",
        "en": "{who} — {distance}{tail}"},
    "deviation.off_route": {
        "uz": "yo'ldan {km} km chetda",
        "ru": "в {km} км от маршрута",
        "en": "{km} km off the route",
    },
    "deviation.unmeasured": {
        "uz": "masofa o'lchanmadi", "ru": "расстояние не измерено",
        "en": "distance not measured"},
    "deviation.route": {
        "uz": "marshrut {number}", "ru": "маршрут {number}", "en": "route {number}"},

    "line.idle": {
        "uz": "{who} — {duration}{tail}", "ru": "{who} — {duration}{tail}",
        "en": "{who} — {duration}{tail}"},
    "idle.standing": {
        "uz": "{hours} soat turibdi", "ru": "простаивает {hours} ч",
        "en": "standing for {hours} h"},
    "idle.unknown": {
        "uz": "davomiyligi noma'lum", "ru": "длительность неизвестна",
        "en": "duration unknown"},
    "idle.engine_on": {
        "uz": "dvigatel ishlab turgan", "ru": "двигатель работает",
        "en": "the engine is running"},

    "line.document": {
        "uz": "{who} — {type} {state}", "ru": "{who} — {type}: {state}",
        "en": "{who} — {type}: {state}"},
    "line.parts": {
        "uz": "{plate} ({vehicle}) — {item}{what}",
        "ru": "{plate} ({vehicle}) — {item}{what}",
        "en": "{plate} ({vehicle}) — {item}{what}"},
    "line.parts_early": {
        "uz": "{plate} ({vehicle}) — {item}: oldingisi resursining atigi {pct}% ini ishlatgan "
              "({used} / {life}, yana {left} xizmat qilishi kerak edi) — almashtirishdan oldin "
              "holatini tekshiring",
        "ru": "{plate} ({vehicle}) — {item}: прежняя деталь выработала лишь {pct}% ресурса "
              "({used} из {life}, могла прослужить ещё {left}) — проверьте перед заменой",
        "en": "{plate} ({vehicle}) — {item}: the previous one used only {pct}% of its life "
              "({used} of {life}, {left} left) — inspect before replacing"},
    "line.service": {
        "uz": "{plate} ({vehicle}) — {component}: {status}, resursning {pct}% i",
        "ru": "{plate} ({vehicle}) — {component}: {status}, {pct}% ресурса",
        "en": "{plate} ({vehicle}) — {component}: {status}, {pct}% of life"},
    "document.expired_days": {
        "uz": "muddati {days} kun oldin o'tgan",
        "ru": "срок истёк {days} дн. назад",
        "en": "expired {days} day(s) ago",
    },
    "document.expired": {
        "uz": "muddati o'tgan", "ru": "срок истёк", "en": "expired"},
    "document.expires_in": {
        "uz": "{days} kundan keyin tugaydi",
        "ru": "истекает через {days} дн.",
        "en": "expires in {days} day(s)",
    },
    "document.unknown": {
        "uz": "muddati noma'lum", "ru": "срок неизвестен",
        "en": "validity unknown"},

    # ------------------------------------------------------------- Navbat
    "queue.baseline.title": {
        "uz": "Kuzatuv boshlandi — rejalashtirishni kutayotgan arizalar",
        "ru": "Наблюдение начато — заявки, ожидающие планирования",
        "en": "Monitoring started — requests awaiting planning",
    },
    "queue.baseline.text": {
        "uz": "Navbatda {total} ta ariza bor, ulardan {overdue} tasi rejadagi "
              "jo'nash vaqtini o'tkazib yuborgan. Hozirgi holat yozib olindi; "
              "bundan keyin faqat YANGISI xabar qilinadi.",
        "ru": "В очереди {total} заявок, из них {overdue} пропустили плановое "
              "время выезда. Текущее состояние зафиксировано; дальше будет "
              "сообщаться только о НОВЫХ.",
        "en": "There are {total} request(s) in the queue, {overdue} of which "
              "missed their planned departure time. The current state was "
              "recorded; from now on only NEW ones will be reported.",
    },
    "queue.new.title": {
        "uz": "{count} ta yangi ariza rejalashtirishni kutmoqda",
        "ru": "{count} новых заявок ожидают планирования",
        "en": "{count} new request(s) are awaiting planning",
    },
    "queue.new.text": {
        "uz": "Navbatda jami {total} ta ariza.",
        "ru": "Всего в очереди {total} заявок.",
        "en": "There are {total} request(s) in the queue in total.",
    },
    "queue.overdue.title": {
        "uz": "{count} ta ariza jo'nash vaqtini o'tkazib yubordi",
        "ru": "{count} заявок пропустили время выезда",
        "en": "{count} request(s) missed their departure time",
    },
    "queue.overdue.text": {
        "uz": "Bu arizalar hali birorta mashinaga berilmagan, rejadagi jo'nash "
              "vaqti esa o'tib bo'ldi.",
        "ru": "Эти заявки ещё не назначены ни на одну машину, а плановое время "
              "выезда уже прошло.",
        "en": "These requests have not been assigned to any vehicle yet, and "
              "their planned departure time has already passed.",
    },
    "queue.hint.full": {
        "uz": "To'liq navbat: {endpoint}",
        "ru": "Полная очередь: {endpoint}",
        "en": "Full queue: {endpoint}",
    },
    "queue.note.limit": {
        "uz": "Chegaraga yetildi ({limit}) — navbat qirqilgan bo'lishi mumkin",
        "ru": "Достигнут лимит ({limit}) — очередь могла быть обрезана",
        "en": "The limit was reached ({limit}) — the queue may have been truncated",
    },
    "queue.note.empty": {
        "uz": "`transport_request` bo'sh — navbat TEKSHIRILMADI",
        "ru": "`transport_request` пуст — очередь НЕ ПРОВЕРЯЛАСЬ",
        "en": "`transport_request` is empty — the queue was NOT CHECKED",
    },
    "queue.line": {
        "uz": "{number} ({priority}) {type}",
        "ru": "{number} ({priority}) {type}",
        "en": "{number} ({priority}) {type}",
    },
    "queue.waited_days": {
        "uz": "{days} kun kutdi", "ru": "ждёт {days} дн.",
        "en": "waited {days} day(s)"},
    "queue.waited_hours": {
        "uz": "{hours} soat kutdi", "ru": "ждёт {hours} ч",
        "en": "waited {hours} h"},
    "queue.overdue_by": {
        "uz": "jo'nash vaqti {hours} soat oldin o'tgan",
        "ru": "время выезда прошло {hours} ч назад",
        "en": "departure time passed {hours} h ago",
    },

    # -------------------------------------------------------------- Reja
    "plan.ready.title": {
        "uz": "Reja tayyor — {assigned} ta ariza taqsimlandi, TASDIQLASH kerak",
        "ru": "План готов — распределено {assigned} заявок, нужно ПОДТВЕРЖДЕНИЕ",
        "en": "The plan is ready — {assigned} request(s) assigned, APPROVAL needed",
    },
    "plan.ready.text": {
        "uz": "{assigned} ta ariza {vehicles} ta mashinaga taqsimlandi, "
              "jami {km} km.",
        "ru": "{assigned} заявок распределено на {vehicles} машин, "
              "всего {km} км.",
        "en": "{assigned} request(s) were assigned to {vehicles} vehicle(s), "
              "{km} km in total.",
    },
    "plan.ready.hint": {
        "uz": "Ko'rish: GET /agent/proposals/{id}  ·  "
              "Tasdiqlash: POST /agent/proposals/{id}/decision",
        "ru": "Посмотреть: GET /agent/proposals/{id}  ·  "
              "Подтвердить: POST /agent/proposals/{id}/decision",
        "en": "View: GET /agent/proposals/{id}  ·  "
              "Approve: POST /agent/proposals/{id}/decision",
    },
    "plan.blocked.title": {
        "uz": "Reja tuzib bo'lmadi — {queued} ta ariza navbatda qolmoqda",
        "ru": "План построить не удалось — {queued} заявок остаются в очереди",
        "en": "The plan could not be built — {queued} request(s) remain queued",
    },
    "plan.blocked.text": {
        "uz": "Optimizator {considered} ta arizani ko'rdi, birortasini ham "
              "joylashtira olmadi. Sabab — {reasons}. Quyidagilar to'ldirilsa "
              "reja O'ZI chiqa boshlaydi, kod o'zgarmaydi.",
        "ru": "Оптимизатор рассмотрел {considered} заявок и не смог разместить "
              "ни одной. Причина — {reasons}. Если заполнить перечисленное, "
              "план начнёт строиться САМ, без изменения кода.",
        "en": "The optimizer looked at {considered} request(s) and could not "
              "place a single one. Reason — {reasons}. Once the items below are "
              "filled in, the plan will start coming out BY ITSELF, with no "
              "code change.",
    },
    "plan.blocked.unknown_reason": {
        "uz": "aniqlanmadi", "ru": "не определена", "en": "not determined"},
    "plan.blocked.hint": {
        "uz": "Batafsil: POST /route-optimization/plan -> data_quality.requirements",
        "ru": "Подробно: POST /route-optimization/plan -> data_quality.requirements",
        "en": "Details: POST /route-optimization/plan -> data_quality.requirements",
    },
    "line.route": {
        "uz": "{who} — {count} ta ariza",
        "ru": "{who} — заявок: {count}",
        "en": "{who} — {count} request(s)",
    },
    "route.km": {"uz": "{km} km", "ru": "{km} км", "en": "{km} km"},
    "route.hours": {"uz": "{hours} soat", "ru": "{hours} ч", "en": "{hours} h"},

    # ---------------------------------------------------- Javob beruvchi
    "responder.title": {
        "uz": "Dispetcher xulosasi — {count} ta yangilik",
        "ru": "Сводка для диспетчера — {count} новостей",
        "en": "Dispatcher summary — {count} update(s)",
    },
    "responder.more": {
        "uz": "{title}. Bundan tashqari yana {count} ta o'zgarish bor.",
        "ru": "{title}. Кроме того, есть ещё {count} изменений.",
        "en": "{title}. There are also {count} more change(s).",
    },
}
