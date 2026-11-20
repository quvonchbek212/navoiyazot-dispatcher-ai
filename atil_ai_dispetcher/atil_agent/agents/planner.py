"""Reja taklifini tayyorlaydigan agent.

NIMA QILADI:
  1. navbatni o'qiydi (`queue_agent` bilan BIR XIL manbadan)
  2. `Marshrut_optimizatsiyasi` ni chaqirib reja tuzdiradi
  3. reja chiqsa — uni TAKLIF qilib qo'yadi (odam tasdiqlaydi)
  4. reja chiqmasa — NIMA YETISHMAYOTGANINI aytadi

3 va 4 — bir xil ahamiyatli. 03.09.2026 da reja chiqmaydi: 33 ta
arizaning hech birida koordinata yo'q (`NO_COORDINATES`) va 84 ta
mashinaning turgan joyi noma'lum. Agent bunda "reja chiqmadi" deb jim
turmaydi, balki QAYSI JADVAL VA QAYSI USTUN to'ldirilishi kerakligini
aytadi — buni `Marshrut_optimizatsiyasi/readiness.py` hisoblab beradi.
Ma'lumot kiritilgan sari reja o'zi chiqa boshlaydi, KOD O'ZGARMAYDI.

TASDIQLASHSIZ HECH NARSA BAJARILMAYDI — va bajarilishi ham mumkin emas:
ATIL bazasiga yozish huquqi yo'q. "Tasdiqlandi" so'zi bu yerda
"bajarildi" degani EMAS.

BIR XIL REJA QAYTA TAKLIF QILINMAYDI. Ilgari reja chiqqan har yurishda
yangi taklif yaratilardi va yangi "TASDIQLASH kerak" xabari ketardi —
navbat ham, reja ham o'zgarmagan bo'lsa ham, soatiga bir marta. Bundan
tashqari yangi taklif eskisini `SUPERSEDED` qilardi, ya'ni dispetcher
bir soat oldin ko'rgan xabardagi tasdiqlash havolasi 409 qaytarardi.
Endi rejaning barmoq izi solishtiriladi (`_plan_fingerprint`).
"""

from __future__ import annotations

import hashlib
import logging
import uuid
from typing import Any

from fastapi.concurrency import run_in_threadpool

from atil_ai_dispetcher.atil_agent import brain, channels, config, state, texts
from atil_ai_dispetcher.atil_agent.texts import spec
from atil_ai_dispetcher.atil_agent.agents.queue_agent import load_queue
from atil_ai_dispetcher.atil_agent.base import Agent, Cycle, Finding
from atil_ai_dispetcher.Marshrut_optimizatsiyasi import explain as ro_explain
from atil_ai_dispetcher.Marshrut_optimizatsiyasi import optimizer
from atil_ai_dispetcher.Marshrut_optimizatsiyasi.optimizer import NothingToPlan
from atil_ai_dispetcher.Marshrut_optimizatsiyasi.queries import PlanningDataError

logger = logging.getLogger(__name__)

#: REJANING O'ZI o'zgarganini kuzatish uchun.
KIND_PROPOSAL = "backlog_proposal"
#: Reja NIMA UCHUN chiqmayotganini kuzatish uchun — sabab o'zgarganda
#: bir marta aytiladi, har soatda emas.
KIND_BLOCK = "backlog_plan"

PROPOSAL_KIND = "route_plan"


def _text_fingerprint(text: str) -> str:
    return hashlib.sha1(text.encode("utf-8")).hexdigest()[:16]


def plan_fingerprint(payload: dict[str, Any]) -> str:
    """Rejaning O'ZI — bitta kalit bo'lib.

    Solishtiriladigan narsa: QAYSI MASHINAGA QAYSI ARIZALAR tushgani.

    MASOFA VA VAQT IZGA KIRMAYDI: ular kalibrovkadan kelib, o'sha-o'sha
    taqsimotda ham 0.1 km ga tebranishi mumkin. Tebranish yangi taklif
    yasashi kerak emas — qaror ARIZA QAYSI MASHINADA ketishi haqida.
    """
    parts = []
    for route in payload.get("routes") or []:
        kim = route.get("vehicle_id") or route.get("plate_number") or "-"
        arizalar = ",".join(sorted(str(n) for n in (route.get("request_numbers") or [])))
        parts.append(f"{kim}={arizalar}")
    return "PLAN|" + ";".join(sorted(parts))


def blockers(plan: dict[str, Any]) -> list[dict[str, Any]]:
    """Rejani TO'XTATIB turgan talablar (`blocking` va `ready=false`)."""
    dq = plan.get("data_quality") or {}
    return [q for q in (dq.get("requirements") or []) if q.get("blocking") and not q.get("ready")]


def block_fingerprint(plan: dict[str, Any]) -> str:
    """Reja chiqmasligining SABABI — bitta kalit bo'lib.

    Sabab o'zgarmasa xabar takrorlanmaydi. Koordinata to'ldirilib, endi
    boshqa narsa yetishmasa — kalit o'zgaradi va yangi xabar ketadi.
    """
    needs = sorted(str(q.get("need")) for q in blockers(plan))
    reasons = sorted((plan.get("summary") or {}).get("unassigned_reasons") or {})
    return "BLOCK|" + ",".join(needs) + "|" + ",".join(reasons)


def route_line(route: dict[str, Any]) -> dict[str, Any]:
    """Marshrut qatori — KALIT ko'rinishida."""
    who = route.get("plate_number") or str(route.get("vehicle_id"))[:8]
    qoshimcha: list[Any] = []
    if route.get("driver_name"):
        qoshimcha.append(str(route["driver_name"]))
    km = route.get("total_distance_km")
    if km is not None:
        qoshimcha.append(spec("route.km", km=f"{km:.0f}"))
    daqiqa = route.get("total_duration_minutes")
    if daqiqa is not None:
        qoshimcha.append(spec("route.hours", hours=f"{daqiqa / 60:.1f}"))
    return spec(
        "line.route",
        who=who,
        count=len(route.get("request_numbers") or []),
        tail=qoshimcha,
    )


def plan_payload(plan: dict[str, Any], id_by_number: dict[str, str]) -> dict[str, Any]:
    """Taklifga tushadigan qism.

    To'liq hisobot saqlanmaydi: unda har to'xtash uchun koordinata va
    vaqt bor va u holat faylini keraksiz shishirardi. Taklifni ODAM
    o'qiydi va TIZIM bajaradi, shuning uchun ikkalasiga kerak bo'lgani
    qoldiriladi.
    """
    routes = []
    for route in plan.get("routes") or []:
        raqamlar = list(route.get("requests") or [])
        # ID SI TOPILMAGAN ARIZA JIMGINA TASHLANMAYDI.
        #
        # Optimizator va agent bir xil arizalarni BOSHQA tartibda
        # o'qiydi (`created_at` va `priority`), ikkalasida ham
        # `limit RO_MAX_REQUESTS`. Navbat shu chegaradan oshsa ikki
        # to'plam farq qiladi. Ilgari bunday raqam indamay tushib
        # qolardi va tasdiqlangan reja tashqi tizimga ketganda ikkita
        # ariza BAJARILMASDAN yo'qolardi.
        topilmagan = [n for n in raqamlar if n not in id_by_number]
        ogohlar = list(route.get("warnings") or [])
        if topilmagan:
            ogohlar.append(
                f"Bu arizalarning id si agent navbatida topilmadi: "
                f"{', '.join(topilmagan)} — bajaruvchi tizim ularni raqam bo'yicha "
                f"izlashi kerak (sabab: `RO_MAX_REQUESTS` chegarasi)"
            )
        routes.append(
            {
                "vehicle_id": route.get("vehicle_id"),
                "plate_number": route.get("plate_number"),
                "transport_type": route.get("transport_type"),
                "driver_id": route.get("driver_id"),
                "driver_name": route.get("driver_name"),
                "request_numbers": raqamlar,
                "request_ids": [id_by_number[n] for n in raqamlar if n in id_by_number],
                "request_numbers_without_id": topilmagan,
                "stops": len(route.get("stops") or []),
                "total_distance_km": route.get("total_distance_km"),
                "total_duration_minutes": route.get("total_duration_minutes"),
                "capacity_utilization": route.get("capacity_utilization"),
                "starts_at": route.get("starts_at"),
                "ends_at": route.get("ends_at"),
                "warnings": ogohlar,
                "explanation": route.get("explanation") or "",
            }
        )
    return {
        "summary": plan.get("summary") or {},
        "routes": routes,
        "unassigned": [
            {
                "request_number": u.get("request_number"),
                "request_id": u.get("request_id"),
                "priority": u.get("priority"),
                "reason_code": u.get("reason_code"),
                "reason": u.get("reason"),
            }
            for u in (plan.get("unassigned") or [])
        ],
        "analysis": (plan.get("analysis") or {}).get("text") or "",
        "calibration": plan.get("calibration") or {},
    }


class PlannerAgent(Agent):
    name = "planner"
    kind = KIND_PROPOSAL
    title = "reja taklifi"
    action_url = "/agent/proposals"
    endpoint = "GET /agent/proposals"
    primary_source = "transport_request"
    group = "backlog"

    @property
    def interval_seconds(self) -> int:
        return config.BACKLOG_INTERVAL_SECONDS

    async def run(self, cycle: Cycle) -> list[Finding]:
        store = state.store()
        items = await load_queue(cycle)
        if not items:
            # Navbat bo'sh — rejalashtiradigan narsa yo'q. Bu xato emas
            # va xabar ham emas: `queue` agenti navbat holatini
            # allaqachon kuzatadi.
            return []

        id_by_number = {
            i["request_number"]: i["request_id"] for i in items if i.get("request_number")
        }

        try:
            plan = await run_in_threadpool(optimizer.plan_from_database)
        except NothingToPlan as exc:
            # BU XATO EMAS, HOLAT. Navbat bo'sh emas, lekin optimizator
            # o'z sana filtri bo'yicha ariza topmadi. `errors` ga
            # qo'shilsa boshqaruv qayta urinish rejimiga o'tardi va
            # agent soatiga bir emas, 2 daqiqada bir bazani so'roq
            # qilardi — doimiy ravishda, chunki sana filtri o'z-o'zidan
            # o'zgarmaydi.
            logger.info("Rejalashtiruvchi: %s", str(exc)[:200])
            return []
        except PlanningDataError as exc:
            raise RuntimeError(f"reja uchun bazadan o'qib bo'lmadi: {exc}"[:200]) from exc

        summary = plan.get("summary") or {}
        assigned = int(summary.get("requests_assigned") or 0)
        if assigned > 0:
            return await self._proposal(store, plan, summary, id_by_number, cycle)
        return self._blocked(store, plan, summary, len(items), cycle)

    # ----------------------------------------------------------- Taklif bor

    async def _proposal(
        self,
        store: state.Store,
        plan: dict[str, Any],
        summary: dict[str, Any],
        id_by_number: dict[str, str],
        cycle: Cycle,
    ) -> list[Finding]:
        payload = plan_payload(plan, id_by_number)
        diff = store.plan_diff(KIND_PROPOSAL, [plan_fingerprint(payload)])

        # Reja chiqdi — "nima to'sqinlik qilyapti" kalitini tozalaymiz,
        # keyingi safar to'siq qaytsa qayta aytilsin.
        store.commit_diff(store.plan_diff(KIND_BLOCK, []), now=cycle.now)

        if not diff.has_news:
            # Aynan shu reja allaqachon taklif qilingan. Yangi taklif ham,
            # xabar ham yo'q — mavjud `PENDING` joyida qoladi va uning
            # havolasi ishlayveradi.
            return []

        tahlil = await self._analyze(plan)
        analyzed = bool(tahlil)
        payload["analysis"] = tahlil.get(texts.DEFAULT_LANG, "")
        payload["analysis_by_lang"] = tahlil

        # TAKLIF ID SI OLDINDAN TUZILADI, saqlash esa `commit` ga
        # qoldiriladi. Sabab: xabar taklif havolasini o'z ichiga oladi,
        # ya'ni id xabardan oldin kerak. Lekin taklif xabardan OLDIN
        # saqlansa va jarayon oradagi paytda o'lsa, bazada tasdiqlashni
        # kutayotgan reja qolardi — va u haqda hech kimga xabar
        # ketmasdi, chunki keyingi yurishda barmoq izi "ko'rilgan"
        # bo'lardi. Endi ikkalasi birga saqlanadi yoki birga qolmaydi.
        proposal_id = uuid.uuid4().hex[:12]
        taklif = {
            "id": proposal_id,
            "kind": PROPOSAL_KIND,
            "agent": self.name,
            "title": (
                f"{summary.get('requests_assigned')} ta arizani "
                f"{summary.get('vehicles_used')} ta mashinaga taqsimlash"
            ),
            "summary": {
                "requests_assigned": summary.get("requests_assigned"),
                "requests_unassigned": summary.get("requests_unassigned"),
                "vehicles_used": summary.get("vehicles_used"),
                "total_distance_km": summary.get("total_distance_km"),
                "saved_distance_km": summary.get("saved_distance_km"),
                "saved_percent": summary.get("saved_percent"),
            },
            "analysis_available": analyzed,
            "plan": payload,
        }
        assigned = int(summary.get("requests_assigned") or 0)
        shown = payload["routes"][: config.MAX_ITEMS_IN_MESSAGE]

        def saqla() -> None:
            store.add_proposal(taklif)
            store.commit_diff(diff, now=cycle.now)

        return [
            Finding(
                agent=self.name,
                kind=PROPOSAL_KIND,
                event_type="proposal",
                # Reja — ODAM QARORINI kutayotgan taklif, buzilgan narsa
                # emas.
                severity=channels.INFO,
                title_spec=spec("plan.ready.title", assigned=assigned),
                # Reja tahlilini marshrut moduli uch tilda yozib beradi
                # (`analysis_by_lang`); model ishlamasa shablon qoladi.
                text_lang=payload.get("analysis_by_lang") or {},
                text_spec=spec(
                    "plan.ready.text",
                    assigned=assigned,
                    vehicles=summary.get("vehicles_used"),
                    km=summary.get("total_distance_km"),
                ),
                source="llm" if analyzed else "template",
                line_specs=[route_line(r) for r in shown],
                extra_count=max(0, len(payload["routes"]) - len(shown)),
                count=assigned,
                dedupe_key=f"{self.name}:{PROPOSAL_KIND}:{proposal_id}",
                entity_type="route_plan",
                entity_id=proposal_id,
                action_url=f"/agent/proposals/{proposal_id}",
                hint_spec=spec("plan.ready.hint", id=proposal_id),
                payload={"proposal_id": proposal_id, "plan": payload},
                commit=saqla,
            )
        ]

    # ---------------------------------------------------------- Reja yo'q

    def _blocked(
        self,
        store: state.Store,
        plan: dict[str, Any],
        summary: dict[str, Any],
        navbat: int,
        cycle: Cycle,
    ) -> list[Finding]:
        # Reja izini tozalaymiz: bugun chiqmagan reja ertaga aynan o'sha
        # ko'rinishda qaytsa, u YANGI taklif bo'lishi kerak.
        store.commit_diff(store.plan_diff(KIND_PROPOSAL, []), now=cycle.now)

        diff = store.plan_diff(KIND_BLOCK, [block_fingerprint(plan)])
        qiyinchiliklar = blockers(plan)
        if not diff.has_news:
            store.commit_diff(diff, now=cycle.now)
            return []

        sabablar = ", ".join(
            f"{code}: {n}" for code, n in (summary.get("unassigned_reasons") or {}).items()
        )

        def saqla() -> None:
            store.commit_diff(diff, now=cycle.now)

        return [
            Finding(
                agent=self.name,
                kind=KIND_BLOCK,
                event_type="blocked",
                # Navbat turibdi, reja esa chiqmayapti — ma'lumot
                # to'ldirilmaguncha shunday qoladi.
                severity=channels.WARNING,
                title_spec=spec("plan.blocked.title", queued=navbat),
                text_spec=spec(
                    "plan.blocked.text",
                    considered=summary.get("requests_considered"),
                    reasons=sabablar or spec("plan.blocked.unknown_reason"),
                ),
                # Talab matni MARSHRUT modulining kalitidan quriladi:
                # bu yerda faqat `need` kodi saqlanadi va o'qish paytida
                # tanlangan tilda ochiladi.
                line_specs=[
                    spec("plan.requirement", need=str(q.get("need")))
                    for q in qiyinchiliklar
                ],
                count=navbat,
                dedupe_key=f"{self.name}:blocked:{_text_fingerprint(block_fingerprint(plan))}",
                entity_type="transport_request",
                action_url="/agent/queue",
                hint_spec=spec("plan.blocked.hint"),
                payload={
                    "blockers": [q.get("need") for q in qiyinchiliklar],
                    "unassigned_reasons": summary.get("unassigned_reasons") or {},
                },
                commit=saqla,
            )
        ]

    # ---------------------------------------------------------------- Miya

    async def _analyze(self, plan: dict[str, Any]) -> dict[str, str]:
        """Rejani LLM bilan izohlatadi.

        `/route-optimization/plan` da model javob bermasa endpoint 503
        qaytaradi — u yerda tahlilning O'ZI mahsulot. Agentda esa
        boshqacha: reja ARIFMETIKA bilan tuzilgan va u tahlilsiz ham
        bajariladigan ish. Model yiqilgani uchun tayyor rejani tashlab
        yuborish dispetcherni ma'lumotsiz qoldirardi. Shuning uchun bu
        yerda xato YUTILADI, lekin YASHIRILMAYDI: `analysis_available`
        `false` bo'lib qaytadi.
        """
        if not config.LLM_ENABLED:
            return {}
        # REJA BIR MARTA HISOBLANADI, TAHLIL UCH MARTA. Taqsimot
        # arifmetika — u tildan mustaqil; faqat izoh matni tilga bog'liq.
        natija: dict[str, str] = {}
        for til in texts.LANGS:
            try:
                await ro_explain.analyze(plan, lang=til)
            except Exception as exc:  # noqa: BLE001
                logger.warning(
                    "Reja tahlili modeldan olinmadi (%s): %s", til, str(exc)[:160])
                continue
            matn = (plan.get("analysis") or {}).get("text") or ""
            if matn:
                natija[til] = matn
        return natija
