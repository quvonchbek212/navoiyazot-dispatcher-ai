# Agentlar

Loyihadagi qolgan hamma xizmat **so'ralganda** javob beradi. Bu modul
**hech kim so'ramasa ham** ishlaydi va o'zgarish bo'lganda xabar tayyorlaydi.

## Uch qatlam

```
                     ┌─────────────────┐
                     │   BOSHQARUV     │  orchestrator.py
                     │  kimni qachon,  │  · muddati kelganlarni topadi
                     │  qaysi tartibda │  · modeldan tartib so'raydi
                     └────────┬────────┘  · xatoni ushlaydi
                              │
        ┌──────────┬──────────┼──────────┬──────────┬──────────┐
        ▼          ▼          ▼          ▼          ▼          ▼
    delayed    deviation    idle     document     queue     planner
    kechikish   og'ish   bekor turish  hujjat     navbat     reja
        │          │          │          │          │          │
        └──────────┴──────────┴────┬─────┴──────────┴──────────┘
                                   │  Finding[]
                          ┌────────▼────────┐
                          │ JAVOB BERUVCHI  │  responder.py
                          │  BITTA xabar    │  · tartiblaydi
                          └────────┬────────┘  · model matn yozadi
                                   │
                          GET /agent/notifications
```

| Qatlam | Fayl | Vazifasi |
|---|---|---|
| boshqaruv | `orchestrator.py` | kimni qachon, qaysi tartibda ishga tushirish |
| bajaruvchi | `agents/*.py` | har biri **bitta** vazifa |
| javob beruvchi | `responder.py` | topilmalarni **bitta** xabarga yig'ish |
| miya | `brain.py` | modelga chiqadigan yagona joy |

**Yangi kuzatuv qo'shish:** `agents/` ga bitta fayl yoziladi va uning sinfi
`agents/__init__.py` dagi `REGISTRY` ga qo'shiladi. Boshqa hech qayerga
tegilmaydi — na boshqaruvga, na javob beruvchiga, na routerga, na `.env` ga.

## Model uch qatlamda ham ishlaydi — ikkita chegara bilan

| Qatlam | Model nima qiladi | Model NIMA QILA OLMAYDI |
|---|---|---|
| boshqaruv | tartibni tanlaydi, qo'shimcha vazifa qo'shadi | **muddati kelgan tekshiruvni o'tkazib yubora olmaydi** |
| bajaruvchi | o'z topilmasiga jumla yozadi | **son hisoblay olmaydi** — raqamlar SQL dan |
| javob beruvchi | sarlavha va xatboshi yozadi | **topilmani tashlab yubora olmaydi** — ro'yxatni kod quradi |

**1-chegara: raqamlar SQL dan keladi.** `/dispatcher/delayed` va agent xabari
bir xil sonni ko'rsatishi kerak. Model raqamni qayta hisoblasa panelda bir son,
xabarda boshqasi chiqadi va buni bir marta ko'rgan odam ikkalasiga ham
ishonmay qo'yadi.

**2-chegara: jim qolish taqiqlangan.** Model `order` dan agentni tushirib
qoldirsa, boshqaruv uni **qaytaradi** va buni `/agent/status` dagi
`last_decision.restored` da ko'rsatadi. Sabab: bu modulning butun vazifasi —
hech kim qaramaganda ham kuzatishni davom ettirish. Model "bugun hujjatlarni
tekshirmasa ham bo'ladi" desa, kuzatuv jimgina o'chib qolardi va buni hech kim
sezmasdi, chunki agentning ishi tashqaridan "jim turish" ga o'xshaydi.

**Model yiqilsa hamma qatlam shablon bilan ishlaydi.** Har xabarda `source`
maydoni matnni kim yozganini ochiq ko'rsatadi (`llm` yoki `template`) — model
bir hafta yiqilib yotgan bo'lsa ham buni yashirmaymiz.

## Endpointlar

```
GET    /agent/notifications                WEBSITE SHUNI O'QIYDI
POST   /agent/notifications/{id}/read      o'qilgan deb belgilash
POST   /agent/notifications/read           bir nechtasini yoki hammasini
GET    /agent/status                       uch qatlamning holati
GET    /agent/queue                        kutayotgan arizalar navbati
GET    /agent/events                       diagnostika: yetkazish tafsiloti
POST   /agent/run?agent=all                kutmasdan hoziroq
GET    /agent/proposals                    tasdiq kutayotgan rejalar
POST   /agent/proposals/{id}/decision      tasdiqlash yoki rad etish
DELETE /agent/state                        bazaviy holatni tozalash
```

`POST /agent/run?agent=` bitta vazifa (`delayed`, `deviation`, `idle`,
`document`, `queue`, `planner`), guruh (`watch`, `backlog`) yoki `all` qabul
qiladi.

## Xabar website'ga qanday boradi

ATIL bazasida `notification` jadvali bor va website o'sha qismni ko'rsatadi.
**Lekin bizda unga yozish huquqi yo'q** — ulanish `READ ONLY`, foydalanuvchida
faqat `SELECT`. Shuning uchun agent hech qayerga yubormaydi: xabar bizda turadi
va website uni **so'rab oladi**.

```
GET /agent/notifications?unread=true&since=2026-09-04T11:39:36
```

```json
[{
  "id": "b832773ea38f",
  "created_at": "2026-09-04T11:39:36",
  "read_at": null,
  "severity": "WARNING",
  "title": "2 ta yangi — kechikayotgan reyslar",
  "body": "• R-1042 — 2.4 soat kechikdi (jo'namagan) · 85353CBA · Ergashev A.",
  "agent": "orchestrator",
  "kind": "delayed",
  "event_type": "new",
  "count": 2,
  "source": "template",
  "dedupe_key": "delayed:new:21438ac385914851",
  "entity_type": "trip",
  "entity_id": null,
  "action_url": "/dispatcher/delayed",
  "items": [ ... ],
  "findings": [ ... ]
}]
```

**Bitta yurish — bitta xabar.** Bir yurishda uchta vazifa topilma bersa, ular
BITTA xabarga yig'iladi (`event_type: "cycle"`), lekin `findings[]` da har biri
**alohida** turadi — o'z `title`, `count`, `severity` va `action_url` i bilan.
Reja taklifining tasdiqlash havolasi ayniqsa yo'qolmasligi kerak.

**Tartib tasodifiy emas.** Eng tepada `blind` — "bu ro'yxat umuman
tekshirilmayapti" — turadi, chunki u qolgan hammasini ma'nosiz qiladi:
telematika o'chgan bo'lsa "og'ish yo'q" degan xabar yolg'on bo'ladi.

**Maydon nomlari ATIL `notification` jadvalidan olingan** — `severity`,
`dedupe_key`, `entity_type`, `entity_id`, `entity_number`, `action_url`.
Backend bu javobni o'z jadvaliga ko'chirmoqchi bo'lsa moslashtirish kerak emas.

**Bitta istisno:** `kind` — bizning o'z nomimiz, jadvaldagi `CHECK`
ro'yxatidan emas. U yerdagi 14 ta qiymat ichida "yo'nalishdan og'ish" yoki
"reja tayyor" uchun mos so'z yo'q, boridan birini zo'rlab tanlash esa
website'da **noto'g'ri belgi** ko'rsatardi.

`severity` — `INFO` yoki `WARNING`. **`CRITICAL` ishlatilmaydi:** bazada
1192 ta `INFO` va 654 ta `WARNING` bor, `CRITICAL` esa birorta ham yo'q.

## Modulning butun mantig'i: RO'YXAT emas, O'ZGARISH

03.09.2026 da bazada **73 ta** kechikkan reys va **412 ta** hujjat bor.
Har 15 daqiqada shu ro'yxatni yuborish kuniga **96 ta bir xil xabar**
demakdir. Bunday kanalni odam birinchi kuni o'chirib tashlaydi — va keyin
**haqiqiy hodisani ham ko'rmaydi**.

Shuning uchun agent nimani ko'rganini eslab qoladi (`state.py`) va faqat
**yangi paydo bo'lganini** aytadi.

**Birinchi ishga tushish — bazaviy holat.** Agent birinchi marta ko'rgan
ro'yxatning hammasini "yangi" deb hisoblamaydi: kalitlarni jimgina yozib
qo'yadi va bitta umumiy xabar beradi.

**Bir xil reja qayta taklif qilinmaydi.** Reja barmoq izi solishtiriladi —
qaysi mashinaga qaysi arizalar tushgani (`planner._plan_fingerprint`). Masofa
0.1 km ga tebransa yangi taklif yasalmaydi: qaror *ariza qaysi mashinada
ketishi* haqida.

## Meyor yo'q

| Nima | Qayerdan keladi |
|---|---|
| kechikish | `scheduled_arrival_at < hozir` — solishtirish |
| yo'ldan og'ish | `vehicle_telemetry_state.deviation_threshold_meters` — **bazadan** |
| bekor turish | chegara yo'q, ro'yxat davomiylik bo'yicha saralanadi |
| hujjat | `valid_until < bugun` — sana bilan solishtirish |
| ariza kechikishi | `planned_departure_at < hozir` — solishtirish |
| ariza muhimligi | `atil_ai_dispetcher.Marshrut_optimizatsiyasi.config.PRIORITY_ORDER` |

`.env` dagi soniyalar **yangilanish tezligi**, meyor emas. O'lchangan
(03.09.2026): `delayed` 0.43 s, `deviations` 0.20 s, `idle` 0.25 s,
`documents` 0.27 s, reja 1.10 s.

Yagona sozlanadigan oyna — `AGENT_DOCUMENTS_DAYS`, u ham **bo'sh
qoldirilgan**: "necha kun qolgani xavfli" degan raqamni baza aytmaydi.

## Tekshirilmagan narsa "muammo yo'q" deb ko'rsatilmaydi

`vehicle_telemetry_state` bo'sh, ya'ni `deviation` va `idle` agentlari
**umuman tekshira olmayapti**. Ular buni alohida topilma qilib aytadi —
lekin har 15 daqiqada emas, faqat **holat o'zgarganda**.

**Bu qaror statistikaga tayanmaydi.** `data_quality.row_counts`
`pg_stat_user_tables` dan olinadi va bu bazada u yolg'on gapiradi:

| jadval | `n_live_tup` | haqiqiy `count(*)` |
|---|---|---|
| `driver` | 0 | 206 |
| `transport_vehicle` | 0 | 128 |
| `trip` | 17 | 199 |

Shu songa ishonilsa, agent 412 ta hujjatni tekshirib turib "hujjatlar
tekshirilmayapti" deb xabar berardi. Shuning uchun `queries.has_rows`
`exists` bilan **haqiqiy** so'rov yuboradi. Manba noma'lum bo'lsa ro'yxat
**ko'r deb hisoblanmaydi**: "bilmadim" ni "bo'sh" ga aylantirish — aynan shu
modul ogohlantirib turgan xato.

## Tasdiqlash — bajarish emas

**ATIL bazasiga yozib bo'lmaydi.** Tasdiqlangan reja bazaga **tushmaydi**, u
`AGENT_APPROVAL_WEBHOOK_URL` ga uzatiladi:

| `handoff.status` | Ma'nosi |
|---|---|
| `ok` | reja bajaruvchi tizimga yetkazildi |
| `skipped` | manzil sozlanmagan — qaror **qayd etildi**, hech qayerga ketmadi |
| `error` | uzatib bo'lmadi — qayta yuborish kerak |

`skipped` va `error` da javobda `warning` chiqadi. `decided_by` **majburiy**.

## Fayllar

```
brain.py           modelga chiqadigan yagona joy; yiqilsa shablon
base.py            Finding · Cycle · Agent — qatlamlar orasidagi shartnoma
orchestrator.py    boshqaruv agent + fon halqasi
responder.py       javob beruvchi agent
agents/
  watcher.py       ro'yxat kuzatuvchilarining umumiy asosi
  delayed.py       ┐
  deviation.py     │ har biri ~50 qator: faqat O'Z farqi
  idle.py          │
  document.py      ┘
  queue_agent.py   ariza navbati + `/agent/queue` hisoboti
  planner.py       reja taklifi
config.py          sozlamalar; qaysi raqam "tezlik", qaysi biri "resurs"
state.py           xotira — bazaviy holat, o'qildi/o'qilmadi, atomik yozish
queries.py         bitta SELECT (ariza qancha kutgan) + haqiqiy `exists`
channels.py        log / webhook; notification saqlanadi, yuborilmaydi
router.py          endpointlar
models.py          javob sxemasi
```

Agent **SQL yozmaydi va hisob-kitobni takrorlamaydi**: kechikish va hujjat
muddati `dispatcher_assistant` da, reja `Marshrut_optimizatsiyasi` da
hisoblanadi.

## Ishga tushirish

`.env`:

```
AGENT_ENABLED=on                    # lokalda off
```

**Boshqa hech narsa shart emas.** Website `GET /agent/notifications` ni
o'qiydi va bunga sozlama kerak emas. Modelni o'chirish uchun `AGENT_LLM=off` —
agent baribir ishlaydi, faqat matnni kod yozadi.

**Bir nechta uvicorn worker bilan ishlatmang.** Har worker o'z boshqaruv
halqasini ishga tushiradi va bitta holat fayliga yozadi. `--workers` kerak
bo'lsa `AGENT_ENABLED=off` qo'ying va agentni alohida bitta jarayonda
ishlating.

Sinash:

```
POST /agent/run?agent=all&notify=false
GET  /agent/notifications?unread=false
DELETE /agent/state
```

## Testlar

`tests/test_atil_agent.py` — baza ham, model ham kerak emas (64 ta test).
Eng muhimlari: birinchi ishga tushish xabar bo'roni bo'lmasligi, bir hodisa
ikki marta xabar qilinmasligi, bir xil reja qayta taklif qilinmasligi,
**boshqaruv agent muddati kelgan tekshiruvni o'tkazib yubora olmasligi**,
**model yiqilganda agent ishlashda davom etishi**, "ko'r" qaror statistikaga
emas haqiqiy manbaga tayanishi, qisman xato "sog'lom" deb ko'rsatilmasligi va
uzatilmagan tasdiq ochiq ogohlantirish bilan qaytishi.
