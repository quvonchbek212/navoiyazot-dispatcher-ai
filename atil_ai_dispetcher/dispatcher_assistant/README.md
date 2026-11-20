# Dispetcher yordamchisi

Dispetcher ertalab ko'radigan to'rtta ro'yxat. Har biri **alohida
endpoint**.

```
GET /dispatcher/delayed      kechikayotgan reyslar
GET /dispatcher/deviations   yo'nalishdan og'ayotgan mashinalar
GET /dispatcher/idle         bekor turgan mashinalar
GET /dispatcher/documents    hujjati tugayotgan haydovchi va mashinalar
```

## Nima uchun to'rtta, bitta hisobot emas

| Sabab | Izoh |
|---|---|
| Ro'yxatlar uzun | bitta javobga yig'ilsa kerakli narsani qidirib o'tirasiz |
| Yangilanish tezligi har xil | kechikish har daqiqada, hujjat muddati kuniga bir marta |
| Filtrlar har xil | `min_minutes`, `min_meters`, `days` — umumiy hisobotda aralashardi |
| Mustaqillik | telematika o'chganda faqat ikkitasi bo'sh qaytadi, qolgan ikkitasi ishlayveradi |

Javob konverti to'rttasida ham bir xil, shuning uchun panel ularni
bitta komponent bilan chizadi:

```
generated_at, scope, summary, analysis, items[], data_quality, elapsed_seconds
```

## Ikki qoida — modulning butun mantig'i

### 1. Bo'sh ro'yxat "muammo yo'q" degani EMAS

Bu modulning eng xavfli xatosi shu bo'lardi. Telematika ulanmagani
uchun bo'sh chiqqan "yo'ldan og'ish" ro'yxati dispetcherga "hammasi
joyida" bo'lib ko'rinardi.

Shuning uchun har bir hisobot manba jadvalini tekshiradi va bo'sh bo'lsa
ochiq yozadi:

```json
"analysis": {
  "text": "Ro'yxat bo'sh, lekin bu \"muammo yo'q\" degani EMAS:
           `vehicle_telemetry_state` bo'sh bo'lgani uchun
           yo'nalishdan og'gan mashinalar umuman tekshirilmadi."
}
```

### 2. Meyor o'ylab topilmaydi

| Nima | Qayerdan |
|---|---|
| kechikish | rejadagi vaqtni HOZIRGI vaqt bilan solishtirish — chegara emas, soatning o'zi |
| yo'ldan og'ish | `vehicle_telemetry_state.deviation_threshold_meters` — chegarani telematika xizmati bazaga yozadi |
| bekor turish | "uzoq" degan chegara YO'Q — ro'yxat davomiylik bo'yicha saralanadi |
| hujjat muddati | sananing o'zi; oyna `days` bilan so'rovda beriladi |

Filtrlar (`min_minutes`, `min_meters`, `days`) **sukut bo'yicha o'chiq**.
Kesish qarori chaqiruvchida.

---

## 1. `/dispatcher/delayed` — kechikayotgan reyslar

**Ikki xil kechikish ajratiladi** — bu bir xil vaziyat emas:

| `kind` | Ma'nosi | Dispetcher nima qila oladi |
|---|---|---|
| `NOT_DEPARTED` | jo'nash vaqti o'tgan, mashina hali chiqmagan | hali to'xtata oladi, boshqa mashina bera oladi |
| `LATE_EN_ROUTE` | yo'lda, yetib borish vaqti o'tgan | faqat mijozni ogohlantirish qoladi |

Har qatorda **oxirgi `trip_event`** ko'rsatiladi — reys qayerda to'xtab
qolgani shundan bilinadi.

**Manba:** `trip` + `trip_event` + `route` + `transport_request` +
`transport_vehicle` + `driver`

Filtrlar: `min_minutes`, `kind`, `limit`

## 2. `/dispatcher/deviations` — yo'nalishdan og'ish

**Og'ishni bu endpoint aniqlamaydi.** Uni telematika xizmati aniqlaydi
va `deviation_active` ga yozadi; chegara ham bazada. Bu yerda o'sha
natija o'qiladi.

Nima uchun qayta hisoblanmaydi: telematika xizmati **har bir GPS
nuqtasini** ko'radi, bu endpoint esa faqat oxirgi holatni. Qayta
hisoblansa kamroq ma'lumot bilan boshqa javob chiqib, ikki xil haqiqat
paydo bo'lardi.

**Qo'shimcha o'lchov** — `distance_from_route_meters`: mashinadan
rejadagi yo'lgacha bo'lgan masofa. Nuqtadan NUQTAGACHA emas,
**kesmagacha**: ikki nuqta o'rtasida ketayotgan mashina aks holda
yo'ldan chiqqandek ko'rinardi.

Marshrut nuqtalari `route_points_json` dan, u bo'sh bo'lsa `route_point`
dan. Ikkalasi ham bo'lmasa masofa `null` — **nol emas**, va bunday qator
`min_meters` filtri bilan **kesilmaydi**.

**Manba:** `vehicle_telemetry_state` + `route_point` + `trip` + `route`

Filtrlar: `min_meters`, `limit`

## 3. `/dispatcher/idle` — bekor turgan mashinalar

Davomiylik: `now() - stop_candidate_since`. Ro'yxat shu bo'yicha
saralangan, eng uzog'i tepada.

**Dvigatel holati alohida qaraladi:** `engine_on=true` bo'lsa mashina
turib yoqilg'i yoqyapti. `summary.by_kind` da `ENGINE_ON` /
`ENGINE_OFF` / `UNKNOWN` alohida sanaladi.

**`minutes_since_last_event` ga e'tibor bering.** GPS uzilib qolgan
mashina ham "to'xtagan" bo'lib ko'rinadi. Oxirgi yozuv 3 soat oldin
bo'lsa, bu to'xtash emas, **aloqa yo'qligi**.

**Manba:** `vehicle_telemetry_state` + `trip` + `transport_vehicle` + `driver`

Filtrlar: `min_minutes`, `limit`

## 4. `/dispatcher/documents` — hujjat muddati

**Beshta manba:**

| `document_type` | Manba | Holat (27.08.2026) |
|---|---|---|
| `LICENSE` | `driver.license_valid_until` | 206/206 to'lgan, **3 tasi muddati o'tgan** |
| `MEDICAL_CERTIFICATE` | `driver.medical_certificate_valid_until` | 206/206 |
| `CREDENTIAL` | `driver_credential.expires_at` | bo'sh |
| `VEHICLE_DOCUMENT` | `vehicle_document.expiry_date` | bo'sh |
| `INSURANCE` | `insurance_policy.valid_to` | bo'sh |

`days_left` **manfiy** bo'lsa muddat o'tgan. `summary.expired` da
o'tganlar soni alohida turadi — "tugayotgan" bilan "tugagan" bir xil emas.

### Kunlik ko'riklar ATAYLAB kirmaydi

`medical_inspection` va `vehicle_technical_inspection` bazada
tekshirildi:

```
vehicle_technical_inspection.to_inspected_at = inspected_at + 1 kun (PRE_TRIP)
medical_inspection.to_date                   = inspected_at
```

Ya'ni ular **har kuni yangilanadi** va "ertaga tugaydi" holati normal.
Ro'yxatga qo'shilsa kuniga **200 dan ortiq qator** chiqib, haqiqiy
muammoni ko'mib tashlardi. Reysga chiqishga tayyorlikni
`/vehicle-selection/rank` tekshiradi.

Filtrlar: `days`, `subject_type`, `document_type`, `limit`

---

## Bugungi holat (27.08.2026)

| Endpoint | Holat |
|---|---|
| `/delayed` | **ishlaydi** — 25 ta kechikayotgan reys topildi, eng og'iri 196 soat |
| `/documents` | **ishlaydi** — 412 hujjat, 3 tasi muddati o'tgan (eng eskisi 7.5 yil) |
| `/deviations` | manba bo'sh — `vehicle_telemetry_state` 0 qator |
| `/idle` | manba bo'sh — o'sha sabab |

Oxirgi ikkitasi **kod tayyor**, faqat GPS integratsiyasi ulanishini
kutyapti. Jadval to'lgan kuni kodga tegmasdan ishlay boshlaydi.

## Fayllar

| Fayl | Vazifasi |
|---|---|
| `config.py` | `.env` sozlamalari (faqat resurs chegaralari) |
| `models.py` | javob sxemasi — to'rt hisobot, bitta konvert |
| `queries.py` | faqat `SELECT`, READ ONLY tranzaksiyada |
| `rules.py` | masofa hisobi va `route_points_json` o'qish — sof funksiyalar |
| `service.py` | orkestratsiya, javob yig'ish |
| `explain.py` | shablon xulosasi + LLM |
| `router.py` | to'rtta FastAPI endpointi |

Testlar: `tests/test_dispatcher_assistant.py` (baza va model kerak emas).

## LLM ning roli

**Ro'yxatga tegmaydi.** Ro'yxatni SQL va solishtirish quradi.

LLM tayyor ro'yxatni **bir xatboshi** qilib xulosalaydi: nima eng
shoshilinch, kimdan boshlash kerak, nima tekshirilmagan. Ollama o'chgan
bo'lsa `analysis.source` `"template"` bo'lib qoladi va javob baribir
to'liq. Shoshilinch so'rovda `?analyze=false`.
