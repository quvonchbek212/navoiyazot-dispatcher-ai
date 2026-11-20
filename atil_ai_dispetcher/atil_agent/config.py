"""Agent sozlamalari.

MEYOR O'YLAB TOPILMAYDI — bu modulda ham. Agent "nima muhim" degan
qarorni O'ZI qabul qilmaydi: u nimani kuzatishini `dispatcher_assistant`
va `Marshrut_optimizatsiyasi` allaqachon hisoblab beradi, agent esa
faqat NIMA O'ZGARGANINI topadi.

Bu yerdagi raqamlar ikki xil, va ular ARALASHTIRILMASLIGI kerak:

  YANGILANISH TEZLIGI   `*_INTERVAL_SECONDS` — necha soniyada bir
                        tekshirilsin. Bu bazaga tushadigan yuk haqidagi
                        qaror, "kechikish muhimmi" haqidagi emas.
                        O'lchangan (03.09.2026, ATIL bazasi):
                            delayed     0.43 s
                            deviations  0.20 s
                            idle        0.25 s
                            documents   0.27 s
                            reja tuzish 1.10 s
                        Ya'ni 900 s da bir tekshirish bazani vaqtning
                        0.13% ida band qiladi. Raqam `.env` da bemalol
                        o'zgartiriladi — hech qanday mantiq unga
                        bog'lanmagan.

  RESURS CHEGARASI      `SCAN_LIMIT`, `MAX_ITEMS_IN_MESSAGE`,
                        `EVENT_HISTORY` — xotira va xabar hajmi.

BU YERDA "30 DAQIQADAN KO'P KECHIKISH", "3 KUNDAN KO'P KUTGAN ARIZA"
KABI QIYMAT YO'Q va bo'lmaydi ham. Yagona istisno — `DOCUMENTS_DAYS`,
u ham SUKUT BO'YICHA BO'SH: to'ldirilmasa agent faqat MUDDATI O'TGAN
hujjatni hodisa deb biladi (bu sana bilan solishtirish, chegara emas).
"""

from __future__ import annotations

import os
from pathlib import Path

from dotenv import load_dotenv

PROJECT_ROOT = Path(__file__).resolve().parents[2]

load_dotenv(PROJECT_ROOT / ".env")


def _int(name: str, default: int) -> int:
    raw = os.getenv(name)
    try:
        return int(raw) if raw not in (None, "") else default
    except ValueError:
        return default


def _opt_int(name: str) -> int | None:
    """Sukut qiymati YO'Q sozlama.

    Bo'sh qoldirilsa `None` qaytadi — va bu "cheksiz" degani emas,
    "bunday chegara belgilanmagan" degani. Chaqiruvchi `None` ni
    o'ziga qarab talqin qiladi.
    """
    raw = os.getenv(name)
    if raw is None or not raw.strip():
        return None
    try:
        return int(raw)
    except ValueError:
        return None


def _flag(name: str, default: bool) -> bool:
    raw = os.getenv(name)
    if raw is None:
        return default
    return raw.strip().lower() in {"1", "true", "yes", "on"}


def _text(name: str, default: str = "") -> str:
    return (os.getenv(name) or default).strip()


# =====================================================================
# Yoqish/o'chirish
# =====================================================================
#: Fon rejasi. SUKUT BO'YICHA O'CHIQ — `main.py` ni import qilishning
#: o'zi hech qayerga xabar yubormasligi kerak (test, migratsiya, lokal
#: ishlab chiqish). Serverda `.env` da `AGENT_ENABLED=on`.
ENABLED = _flag("AGENT_ENABLED", False)

#: Har bir agentni alohida o'chirish. `ENABLED=off` bo'lsa ikkalasi
#: ham ishlamaydi — bular faqat qo'shimcha kalit.
WATCH_ENABLED = _flag("AGENT_WATCH_ENABLED", True)
BACKLOG_ENABLED = _flag("AGENT_BACKLOG_ENABLED", True)

# =====================================================================
# Yangilanish tezligi (meyor EMAS)
# =====================================================================
#: Kechikish, og'ish va bekor turish — bular daqiqalar ichida o'zgaradi
#: (`dispatcher_assistant/README.md`).
WATCH_INTERVAL_SECONDS = _int("AGENT_WATCH_INTERVAL_SECONDS", 900)

#: Hujjat muddati — SANA. U yarim tundan boshqa paytda o'zgara olmaydi,
#: shuning uchun kuniga bir marta yetadi. 15 daqiqada tekshirish bir xil
#: javobni 96 marta olib kelardi.
DOCUMENTS_INTERVAL_SECONDS = _int("AGENT_DOCUMENTS_INTERVAL_SECONDS", 86400)

#: Ariza navbati — ariza ish kuni davomida kelib turadi.
BACKLOG_INTERVAL_SECONDS = _int("AGENT_BACKLOG_INTERVAL_SECONDS", 3600)

#: Xato bo'lgandan keyin qayta urinishgacha kutish. Baza yiqilganda
#: har 900 s da emas, tezroq qaytib kelish uchun — lekin uzluksiz
#: urinib bazani bo'g'masligi uchun ham.
RETRY_INTERVAL_SECONDS = _int("AGENT_RETRY_INTERVAL_SECONDS", 120)

# =====================================================================
# Hujjat hodisasining ta'rifi
# =====================================================================
#: Muddati tugashigacha shuncha kun qolganda hodisa deb hisoblansin.
#: SUKUT BO'YICHA BO'SH — "necha kun qolgani xavfli" degan raqamni baza
#: aytmaydi va u shu yerda O'YLAB TOPILMAYDI.
#:
#: Bo'sh qolsa agent faqat MUDDATI O'TGAN hujjat haqida xabar beradi:
#: `valid_until < bugun` — bu chegara emas, sana bilan solishtirish.
#:
#: 03.09.2026 da bazada: 412 ta hujjat, ulardan muddati o'tgani 2 ta,
#: eng yaqin tugaydigani 52 kundan keyin. Ya'ni bo'sh qoldirilganda
#: agent bugun 2 ta xabar beradi, 412 ta emas.
DOCUMENTS_DAYS = _opt_int("AGENT_DOCUMENTS_DAYS")

#: Qism kuzatuvchisi shuncha OXIRGI kunni ko'radi. Bu meyor emas, OYNA:
#: yangi qism so'rovi shu ichida paydo bo'ladi. Oynadan chiqib ketgan holat
#: "yo'qoldi" deb xabar qilinmaydi — agent faqat YANGI paydo bo'lganini aytadi.
PARTS_WINDOW_DAYS = _int("AGENT_PARTS_WINDOW_DAYS", 30)

# =====================================================================
# Resurs chegaralari
# =====================================================================
#: Solishtirish uchun bazadan o'qiladigan qatorlar soni. Xabarga emas,
#: TAQQOSLASHGA kerak: ro'yxat qirqilsa, qirqilgan qism "yo'qoldi" deb
#: ko'rinib, keyingi safar "yangi" bo'lib qaytardi.
SCAN_LIMIT = _int("AGENT_SCAN_LIMIT", 5000)

#: Bitta xabarga sig'adigan qatorlar. Qolgani "yana N ta" bo'lib
#: yoziladi va to'liq ro'yxat `/dispatcher/*` da qoladi.
MAX_ITEMS_IN_MESSAGE = _int("AGENT_MAX_ITEMS_IN_MESSAGE", 10)

#: Xotirada saqlanadigan hodisa va taklif tarixi.
EVENT_HISTORY = _int("AGENT_EVENT_HISTORY", 200)
PROPOSAL_HISTORY = _int("AGENT_PROPOSAL_HISTORY", 50)

#: Holat fayli. Bazaga YOZIB BO'LMAYDI (ATIL ulanishi READ ONLY,
#: foydalanuvchida faqat SELECT), suhbat tarixi bazasi esa `.env` da
#: yozilganidek ishlamayapti. Shuning uchun holat oddiy faylda.
STATE_PATH = Path(
    _text("AGENT_STATE_PATH") or str(PROJECT_ROOT / "atil_ai_dispetcher" / "atil_agent" / "state" / "agent_state.json")
)

# =====================================================================
# Yetkazish kanallari
# =====================================================================
#: NOTIFICATION va LOG — HAR DOIM yoqiq va o'chirib bo'lmaydi.
#: Notification bu yerda SOZLAMA TALAB QILMAYDI: hodisa agent
#: xotirasiga yoziladi va `GET /agent/notifications` da turadi, ATIL
#: website o'sha yerdan o'qib oladi. Ya'ni "manzil" degan narsa yo'q —
#: o'qiydigan tomon bizga keladi.
#:
#: Webhook esa TASHQARIGA chiqadi (n8n, ERP), shuning uchun faqat
#: `.env` da manzil yozilgandagina ishlaydi. Sukut bo'yicha jim.
WEBHOOK_URL = _text("AGENT_WEBHOOK_URL")
WEBHOOK_TIMEOUT_SECONDS = _int("AGENT_WEBHOOK_TIMEOUT_SECONDS", 10)

#: Taklif TASDIQLANGANDA qayerga yuborilsin. ATIL bazasiga yozib
#: bo'lmaydi, shuning uchun tasdiq shu manzilga (ATIL API, n8n, ERP)
#: uzatiladi. Bo'sh bo'lsa qaror faqat qayd etiladi — va javobda buni
#: ochiq aytamiz, "bajarildi" deb ko'rsatmaymiz.
APPROVAL_WEBHOOK_URL = _text("AGENT_APPROVAL_WEBHOOK_URL")

# =====================================================================
# LLM — uch qatlamning uchalasida ham
# =====================================================================
#: Model umuman ishlatilsinmi.
#:
#: O'CHIRILSA AGENT ISHLASHDA DAVOM ETADI. Har uch qatlamda modelning
#: o'rniga kod hisoblagan javob ishlatiladi:
#:
#:   boshqaruv      agentlar sukut tartibida ishlaydi
#:   bajaruvchi     xabar matni shablondan quriladi
#:   javob beruvchi sarlavha va xatboshi shablondan quriladi
#:
#: Ya'ni bu sozlama "agent ishlaydimi" degan savolga tegishli emas,
#: "xabarni kim yozadi" degan savolga tegishli. Har hodisada `source`
#: maydoni qaysi biri bo'lganini ochiq ko'rsatadi.
LLM_ENABLED = _flag("AGENT_LLM", _flag("AGENT_LLM_SUMMARY", True))

#: Bitta chaqiruv shuncha soniyada javob bermasa — shablonga o'tamiz.
#:
#: NIMA UCHUN CHEGARA BOR. Agent fon oqimida ishlaydi va hech kim javob
#: kutib turmaydi, lekin bitta yurish ichida 6 tagacha chaqiruv bo'lishi
#: mumkin. Model sekinlashsa yurish 15 daqiqalik oraliqdan uzunroq
#: cho'zilib, keyingi yurishni bosib ketardi.
LLM_TIMEOUT_SECONDS = _int("AGENT_LLM_TIMEOUT_SECONDS", 45)

#: Modelga nechta qator ko'rsatiladi. Uzunroq prompt = sekinroq javob;
#: modelga ro'yxatni QAYTA YOZISH uchun emas, kontekst uchun beriladi.
LLM_FACT_LIMIT = _int("AGENT_LLM_FACT_LIMIT", 10)
