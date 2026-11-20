"""Agent xotirasi — nimani allaqachon aytgan bo'lsa, qaytarmaydi.

NIMA UCHUN BU FAYL BOR. Agent har 15 daqiqada bir xil ro'yxatni ko'radi:
bugun 73 ta kechikkan reys, 412 ta hujjat. Xotirasiz agent ularni HAR
SAFAR qaytadan xabar qilardi — bir kunda 96 ta bir xil xabar. Bunday
tizimni odam bir kunda o'chirib tashlaydi va keyin HAQIQIY hodisani ham
ko'rmaydi. Shuning uchun agentning butun qiymati shu faylda: u
RO'YXATNI emas, O'ZGARISHNI xabar qiladi.

NIMA UCHUN FAYL, BAZA EMAS:
  * ATIL bazasiga yozib bo'lmaydi — ulanish READ ONLY va bazadagi
    foydalanuvchida faqat SELECT huquqi bor;
  * suhbat tarixi bazasi (`CHAT_DB_*`) `.env` da yozilganidek hozir
    ishlamayapti va uni agent ishlashi uchun shart qilib qo'yish
    kuzatuvni butunlay to'xtatib qo'yardi.
Fayl kichik (bir necha yuz kalit) va jarayon bitta — bu ish uchun
yetarli.

BIRINCHI ISHGA TUSHISH — BAZAVIY HOLAT. Agent birinchi marta ko'rgan
ro'yxatning hammasini "yangi" deb hisoblamaydi: u kalitlarni jimgina
yozib qo'yadi va faqat BITTA umumiy xabar beradi ("kuzatuv boshlandi,
hozir shuncha bor"). Aks holda birinchi ishga tushishning o'zi 412 ta
xabar yuborardi.

KAMIDA BIR MARTA (at-least-once). Kalitlar xabar YOZILGANDAN keyin
saqlanadi. Jarayon shu oraliqda o'lsa, keyingi ishga tushishda o'sha
hodisa qayta xabar qilinadi. Teskarisi — avval saqlab, keyin xabar
qilish — hodisani BUTUNLAY yo'qotardi, va yo'qolgan ogohlantirish
takrorlangandan xavfliroq.
"""

from __future__ import annotations

import copy
import json
import logging
import os
import threading
import uuid
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any, Iterable

from atil_ai_dispetcher.atil_agent import config

logger = logging.getLogger(__name__)

#: Fayl formati raqami. O'zgarganda eski fayl o'qilmaydi va bazaviy
#: holat qaytadan quriladi — bu xabar bo'ronidan ko'ra tushunarliroq
#: (bir marta "kuzatuv boshlandi" keladi).
#:
#: 3 — hodisaga `severity`, `dedupe_key` va `read_at` qo'shildi
#:     (website notification qismi shu maydonlarni o'qiydi).
VERSION = 3

PENDING = "PENDING"
APPROVED = "APPROVED"
REJECTED = "REJECTED"
SUPERSEDED = "SUPERSEDED"


def _now_iso(now: datetime | None = None) -> str:
    return (now or datetime.now()).isoformat(timespec="seconds")


@dataclass
class Diff:
    """Bitta ro'yxatning oldingi holat bilan farqi.

    `baseline` — bu ro'yxat birinchi marta ko'rilyapti. Bunda `new`
    to'la bo'ladi, lekin uni QATOR-QATOR xabar qilish mumkin emas.
    """

    kind: str
    new_keys: list[str] = field(default_factory=list)
    gone_keys: list[str] = field(default_factory=list)
    current_keys: list[str] = field(default_factory=list)
    baseline: bool = False

    @property
    def has_news(self) -> bool:
        return bool(self.new_keys)


class Store:
    """Holat fayli ustidagi yagona kirish nuqtasi (jarayonda bitta nusxa)."""

    def __init__(self, path: Path):
        self._path = path
        self._lock = threading.RLock()
        self._data = self._load()

    # ------------------------------------------------------------ Fayl

    def _empty(self) -> dict[str, Any]:
        return {
            "version": VERSION,
            "updated_at": _now_iso(),
            "kinds": {},
            "runs": {},
            "events": [],
            "proposals": [],
        }

    def _load(self) -> dict[str, Any]:
        if not self._path.exists():
            return self._empty()
        try:
            data = json.loads(self._path.read_text(encoding="utf-8"))
        except (OSError, ValueError) as exc:
            # BUZILGAN FAYL O'CHIRILMAYDI, chetga surib qo'yiladi: nima
            # bo'lganini keyin ko'rish mumkin bo'lsin. Yangi bazaviy
            # holat quriladi, ya'ni bir marta "kuzatuv boshlandi" keladi.
            backup = self._path.with_suffix(f".corrupt-{int(datetime.now().timestamp())}.json")
            try:
                self._path.replace(backup)
                logger.error("Agent holati o'qilmadi (%s) — eski fayl: %s", exc, backup)
            except OSError:
                logger.error("Agent holati o'qilmadi (%s) va chetga surilmadi", exc)
            return self._empty()

        if not isinstance(data, dict) or data.get("version") != VERSION:
            logger.warning(
                "Agent holati boshqa formatda (%s) — bazaviy holat qaytadan quriladi",
                data.get("version") if isinstance(data, dict) else type(data).__name__,
            )
            return self._empty()
        # Kalitlar yo'q bo'lsa to'ldiramiz — qo'lda tahrirlangan fayl
        # butun agentni yiqitmasin.
        for key, default in (("kinds", {}), ("runs", {}), ("events", []), ("proposals", [])):
            data.setdefault(key, default)
        return data

    def _save(self) -> None:
        """Atomik yozish.

        Vaqtinchalik faylga yozib, keyin `os.replace` bilan almashtiramiz.
        To'g'ridan-to'g'ri yozilsa, aynan yozish paytida jarayon o'lganda
        fayl yarim qolib buzilardi va butun tarix yo'qolardi.
        """
        self._data["updated_at"] = _now_iso()
        try:
            self._path.parent.mkdir(parents=True, exist_ok=True)
            tmp = self._path.with_suffix(".tmp")
            tmp.write_text(
                json.dumps(self._data, ensure_ascii=False, indent=2, default=str),
                encoding="utf-8",
            )
            os.replace(tmp, self._path)
        except OSError as exc:
            # Yozilmasa ham agent ishlashda davom etadi — xotiradagi
            # holat to'g'ri. Faqat qayta ishga tushirishda takror xabar
            # bo'lishi mumkin, va buni log aytib turadi.
            logger.error("Agent holati saqlanmadi (%s): %s", self._path, exc)

    # ------------------------------------------------------- Ro'yxat farqi

    def _kind(self, kind: str) -> dict[str, Any]:
        return self._data["kinds"].setdefault(
            kind, {"baseline_at": None, "last_run_at": None, "blind": None, "seen": {}}
        )

    def plan_diff(self, kind: str, keys: Iterable[str]) -> Diff:
        """Farqni HISOBLAYDI, lekin saqlamaydi.

        Saqlash `commit_diff` da — xabar yozilgandan keyin. Ikkiga
        bo'linishining sababi fayl boshidagi "kamida bir marta"
        izohida.
        """
        with self._lock:
            state = self._kind(kind)
            seen = state["seen"]
            current = list(dict.fromkeys(str(k) for k in keys))  # tartibni saqlab, takrorsiz
            current_set = set(current)
            return Diff(
                kind=kind,
                new_keys=[k for k in current if k not in seen],
                gone_keys=[k for k in seen if k not in current_set],
                current_keys=current,
                baseline=state["baseline_at"] is None,
            )

    def commit_diff(self, diff: Diff, *, now: datetime | None = None) -> None:
        """Farqni holatga yozadi.

        Yo'qolgan kalitlar O'CHIRILADI — aks holda fayl cheksiz o'sardi
        va bir marta tugagan reys abadiy "ko'rilgan" bo'lib qolardi
        (o'sha reys raqami qayta ishlatilsa xabar berilmasdi).
        """
        stamp = _now_iso(now)
        with self._lock:
            state = self._kind(diff.kind)
            seen: dict[str, str] = state["seen"]
            for key in diff.gone_keys:
                seen.pop(key, None)
            for key in diff.new_keys:
                seen[key] = stamp
            state["last_run_at"] = stamp
            if state["baseline_at"] is None:
                state["baseline_at"] = stamp
            self._save()

    def blind_state(self, kind: str) -> bool | None:
        """Oxirgi marta bu ro'yxat KO'R deb belgilanganmi.

        `None` — hali hech qachon tekshirilmagan. Bu "ko'r emas" degani
        EMAS: birinchi kuzatuvda "tiklandi" deb yozib bo'lmaydi, chunki
        hech narsa buzilmagan edi.
        """
        with self._lock:
            return self._kind(kind)["blind"]

    def set_blind(self, kind: str, blind: bool) -> None:
        """KO'R holatni saqlaydi — XABAR YOZILGANDAN KEYIN.

        Nima uchun keyin: fayl boshidagi "kamida bir marta" qoidasi shu
        yerda ham amal qiladi. Avval saqlab keyin xabar qilinsa, jarayon
        oradagi paytda o'lganda "TEKSHIRILMAYAPTI" ogohlantirishi
        BUTUNLAY yo'qolardi — holat allaqachon `blind=True` bo'lgani
        uchun keyingi yurish uni o'zgarish deb ko'rmasdi. Yo'qolgan
        ogohlantirish takrorlangandan xavfliroq.
        """
        with self._lock:
            state = self._kind(kind)
            if state["blind"] == blind:
                return
            state["blind"] = blind
            self._save()

    def kind_state(self, kind: str) -> dict[str, Any]:
        with self._lock:
            return copy.deepcopy(self._kind(kind))

    def forget(self, kind: str | None = None) -> None:
        """Bazaviy holatni tozalaydi — keyingi ishga tushish yangidan boshlaydi."""
        with self._lock:
            if kind is None:
                self._data["kinds"] = {}
            else:
                self._data["kinds"].pop(kind, None)
            self._save()

    # ------------------------------------------------------------ Hodisa

    def record_event(self, event: dict[str, Any]) -> dict[str, Any]:
        """Hodisani yozadi — SHU BILAN u notification ham bo'ladi.

        ATIL website `GET /agent/notifications` dan aynan shu yozuvlarni
        o'qiydi. Ya'ni "yuborish" degan qadam yo'q: yozilgan hodisa
        allaqachon yetkazilgan hisoblanadi va tashqi kanal yiqilsa ham
        yo'qolmaydi.
        """
        with self._lock:
            event.setdefault("id", uuid.uuid4().hex[:12])
            event.setdefault("created_at", _now_iso())
            event.setdefault("read_at", None)
            self._data["events"].insert(0, event)
            del self._data["events"][config.EVENT_HISTORY:]
            self._save()
            return copy.deepcopy(event)

    def set_delivery(self, event_id: str, delivery: list[dict[str, Any]]) -> None:
        """Yetkazish natijasini hodisaga yozadi.

        Hodisa AVVAL saqlanadi, kanallar KEYIN chaqiriladi — shuning
        uchun natija alohida yoziladi. Tartib ataylab shunday: webhook
        sekin javob bergan paytda ham hodisa allaqachon website uchun
        o'qishga tayyor turadi.
        """
        with self._lock:
            for row in self._data["events"]:
                if row.get("id") == event_id:
                    row["delivery"] = delivery
                    self._save()
                    return

    def events(
        self,
        limit: int = 50,
        agent: str | None = None,
        *,
        unread_only: bool = False,
        since: str | None = None,
    ) -> list[dict[str, Any]]:
        """Hodisalar — eng yangisi birinchi.

        `since` — ISO vaqt; undan KEYIN yaratilganlari qaytadi. Website
        har safar hammasini emas, faqat yangisini so'rashi uchun. Matn
        bo'yicha solishtiriladi va bu to'g'ri: `isoformat` bir xil
        uzunlikdagi qatorlar beradi, ular leksikografik tartibda ham
        vaqt tartibida turadi.
        """
        with self._lock:
            rows = self._data["events"]
            if agent:
                rows = [e for e in rows if e.get("agent") == agent]
            if unread_only:
                rows = [e for e in rows if not e.get("read_at")]
            if since:
                rows = [e for e in rows if str(e.get("created_at") or "") > since]
            return copy.deepcopy(rows[:limit])

    def unread_count(self, agent: str | None = None) -> int:
        with self._lock:
            return sum(
                1
                for e in self._data["events"]
                if not e.get("read_at") and (agent is None or e.get("agent") == agent)
            )

    def mark_read(self, event_ids: Iterable[str], *, now: datetime | None = None) -> list[str]:
        """Ko'rsatilgan hodisalarni o'qilgan deb belgilaydi.

        ALLAQACHON O'QILGANI QAYTA BELGILANMAYDI — `read_at` birinchi
        o'qilgan payt bo'lib qoladi. Aks holda website ro'yxatni har
        ochganda vaqt suriladi va "qachon ko'rilgan" degan savolga javob
        yo'qolardi.

        Qaytadi: haqiqatan o'zgargan hodisalar id si. Topilmagan id
        jimgina tashlanmaydi — chaqiruvchi ro'yxatni solishtirib
        ko'rishi mumkin.
        """
        wanted = {str(i) for i in event_ids}
        if not wanted:
            return []
        stamp = _now_iso(now)
        changed: list[str] = []
        with self._lock:
            for row in self._data["events"]:
                if row.get("id") in wanted and not row.get("read_at"):
                    row["read_at"] = stamp
                    changed.append(row["id"])
            if changed:
                self._save()
            return changed

    def mark_all_read(self, agent: str | None = None, *, now: datetime | None = None) -> list[str]:
        with self._lock:
            ids = [
                e["id"]
                for e in self._data["events"]
                if not e.get("read_at") and (agent is None or e.get("agent") == agent)
            ]
        return self.mark_read(ids, now=now)

    # ------------------------------------------------------- Ishga tushish

    def record_run(
        self,
        agent: str,
        *,
        ok: bool,
        error: str | None = None,
        elapsed: float | None = None,
        now: datetime | None = None,
    ) -> None:
        stamp = _now_iso(now)
        with self._lock:
            run = self._data["runs"].setdefault(
                agent,
                {"runs": 0, "last_run_at": None, "last_ok_at": None,
                 "last_error": None, "last_error_at": None, "consecutive_errors": 0,
                 "last_elapsed_seconds": None},
            )
            run["runs"] += 1
            run["last_run_at"] = stamp
            run["last_elapsed_seconds"] = None if elapsed is None else round(elapsed, 3)

            # XATO MATNI HECH QACHON JIMGINA TASHLANMAYDI. Ilgari bu yerda
            # `ok` bo'lsa `last_error = None` qilinardi va chaqiruvchi
            # uzatgan xato yo'qolardi — `/agent/status` da 4 ta ro'yxatdan
            # 3 tasi yiqilgan holat "sog'lom" bo'lib ko'rinardi.
            if error:
                run["last_error"] = error[:300]
                run["last_error_at"] = stamp
            else:
                run["last_error"] = None

            if ok:
                run["last_ok_at"] = stamp
                run["consecutive_errors"] = 0
            else:
                run["consecutive_errors"] += 1
            self._save()

    def run_state(self, agent: str) -> dict[str, Any]:
        with self._lock:
            return copy.deepcopy(self._data["runs"].get(agent) or {})

    def runs(self) -> dict[str, Any]:
        with self._lock:
            return copy.deepcopy(self._data["runs"])

    # ------------------------------------------------------------ Taklif

    def add_proposal(self, proposal: dict[str, Any]) -> dict[str, Any]:
        """Yangi taklif qo'shadi va oldingi KUTAYOTGANINI eskirtiradi.

        Bir vaqtning o'zida ikkita kutayotgan reja bo'lishi mumkin emas:
        ular bir xil arizalarni boshqacha taqsimlaydi va ikkalasini
        tasdiqlash bir-biriga zid ikki qaror bo'lardi.
        """
        with self._lock:
            stamp = _now_iso()
            for old in self._data["proposals"]:
                if old.get("status") == PENDING and old.get("kind") == proposal.get("kind"):
                    old["status"] = SUPERSEDED
                    old["decided_at"] = stamp
                    old["note"] = "Yangi reja tuzildi — bu taklif eskirdi"
            proposal.setdefault("id", uuid.uuid4().hex[:12])
            proposal.setdefault("created_at", stamp)
            proposal.setdefault("status", PENDING)
            self._data["proposals"].insert(0, proposal)
            del self._data["proposals"][config.PROPOSAL_HISTORY:]
            self._save()
            return copy.deepcopy(proposal)

    def proposals(self, status: str | None = None, limit: int = 50) -> list[dict[str, Any]]:
        with self._lock:
            rows = self._data["proposals"]
            if status:
                rows = [p for p in rows if p.get("status") == status]
            return copy.deepcopy(rows[:limit])

    def proposal(self, proposal_id: str) -> dict[str, Any] | None:
        with self._lock:
            for row in self._data["proposals"]:
                if row.get("id") == proposal_id:
                    return copy.deepcopy(row)
            return None

    def decide(
        self,
        proposal_id: str,
        *,
        status: str,
        decided_by: str,
        note: str | None = None,
    ) -> dict[str, Any] | None:
        """Taklifni tasdiqlaydi yoki rad etadi.

        FAQAT `PENDING` holatidagi taklif hal qilinadi. Eskirgan yoki
        allaqachon hal qilinganini qayta hal qilish — bir qarorni ikki
        marta qabul qilish bo'lardi; chaqiruvchi buni `None` orqali
        biladi va foydalanuvchiga hozirgi holatni ko'rsatadi.
        """
        with self._lock:
            for row in self._data["proposals"]:
                if row.get("id") != proposal_id:
                    continue
                if row.get("status") != PENDING:
                    return None
                row["status"] = status
                row["decided_at"] = _now_iso()
                row["decided_by"] = decided_by
                row["note"] = note
                self._save()
                return copy.deepcopy(row)
            return None

    def mark_handoff(self, proposal_id: str, handoff: dict[str, Any]) -> None:
        """Tasdiq tashqariga uzatildimi — javobda ochiq ko'rsatish uchun."""
        with self._lock:
            for row in self._data["proposals"]:
                if row.get("id") == proposal_id:
                    row["handoff"] = handoff
                    self._save()
                    return

    # ------------------------------------------------------------- Umumiy

    def snapshot(self) -> dict[str, Any]:
        with self._lock:
            return copy.deepcopy(self._data)


_store: Store | None = None
_store_lock = threading.Lock()


def store() -> Store:
    """Jarayondagi yagona nusxa (kech yaratiladi — import chog'ida fayl ochilmaydi)."""
    global _store
    with _store_lock:
        if _store is None:
            _store = Store(config.STATE_PATH)
        return _store


def reset_for_tests(path: Path) -> Store:
    """Testlar uchun: holatni boshqa faylga ko'chirish."""
    global _store
    with _store_lock:
        _store = Store(path)
        return _store
