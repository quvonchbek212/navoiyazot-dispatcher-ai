# Mashina/haydovchi tanlash

Reysga eng mos **mashina+haydovchi juftliklarini** reytinglaydi.

```
GET /vehicle-selection/rank?route_id=...
GET /vehicle-selection/rank?transport_type=DUMP_TRUCK&driver_category=C
```

Bitta endpoint. Reyting ham, tahlil ham, kesish sabablari ham bitta javobda.

## Olti mezon

| Mezon | Nima o'lchanadi | Manba jadval |
|---|---|---|
| `capacity` | yuk sig'adimi va sig'imdan qanchalik to'liq foydalaniladi | `transport_vehicle` + talab |
| `distance` | mashina yuklash nuqtasiga qanchalik yaqin | `vehicle_telemetry_state` |
| `documents` | hujjatlar jo'nash kuniga amal qiladimi | `vehicle_document`, `insurance_policy`, `driver` |
| `shift` | haydovchi smenasi reys oynasini qoplaydimi | `driver_shift` |
| `skill` | toifa mosligi, tajriba, xavfsizlik tarixi | `driver_license_category`, `trip`, `incident` |
| `technical` | mashina yo'lga yaroqlimi | `vehicle_technical_inspection`, `vehicle_repair`, `maintenance_plan` |

## Uchta qoida — modulning butun mantig'i shu

### 1. `null` — nol emas

Mezonning ma'lumoti bo'lmasa bali `null` bo'ladi, **nol emas**. Sig'imi
ko'rsatilmagan mashina "sig'imi yomon" degani emas. Bunday mezon reytingdan
chiqariladi va **og'irligi qolganlarga qayta taqsimlanadi**.

Nima uchun bu muhim: 22.08.2026 holatiga `payload_capacity_kg` bazadagi 127
mashinaning **127 tasida ham bo'sh**. Agar `null` nolga aylanganda edi,
hamma mashina bir xil jazolangan bo'lardi va reyting ma'nosini yo'qotardi.

Qaysi mezon nima uchun tushib qolgani `summary.criteria_skipped` da ochiq
yoziladi — mezon jimgina yo'qolib qolmaydi.

### 2. Kesish va ball — ikki xil narsa

**Kesish** — umuman mumkin emas. Qonuniy yoki fizik cheklov:

| Sabab | Qayerdan |
|---|---|
| guvohnoma muddati o'tgan | `driver.license_valid_until` |
| toifa mos emas | `driver_license_category` vs `route.required_driver_category` |
| yuk sig'imdan og'ir | `payload_capacity_kg` |
| bloklovchi remont ochiq | `vehicle_repair.blocks_release` |
| band | `trip`, `waybill` |
| tibbiy ko'rik UNFIT / yo'q | `medical_inspection` |
| transport turi mos emas | `transport_vehicle.transport_type` |

**Ball** — 0..1 oralig'ida, faqat kesishdan o'tganlarga.

`include_blocked=true` bilan kesilganlar ham qaytadi va `blockers` da sababi
yoziladi — "nega bu mashina ro'yxatda yo'q" degan savol uchun.

### 3. Bo'shlik bayroqdan olinmaydi

`ddl.sql` izohi *"bo'sh mashinalar `current_status='ACTIVE'` bo'yicha
olinadi"* deydi. **Bu bayroq yangilanmayapti** — 22.08.2026 da bazada
o'lchandi:

| Tekshiruv | Natija |
|---|---|
| aktiv reysdagi 10 haydovchi | 10 tasi ham hali `AVAILABLE` |
| aktiv reysdagi 10 mashina | 10 tasi ham hali `ACTIVE` |
| `driver.medical_cleared_today = true` | 92 ta |
| `medical_inspection` da o'sha kunga `FIT` | **27 ta** |

Shuning uchun bandlik **hodisa jadvallaridan** olinadi: `trip` (aktiv
holatlar) va `waybill` (ochiq holatlar), **ikkalasining birlashmasi** —
bittasi band desa band. Bayroqlar javobda ko'rinadi (`availability_flag`,
`current_status`), lekin qaror ular bilan chiqarilmaydi.

## Chegara yo'q — nisbat bor

Kodda birorta ham o'ylab topilgan meyor yo'q. "50 km uzoq", "30 kun qolgani
xavfli" degan raqamlar o'rniga:

- **Masofa va hujjat muddati** — nomzodlar bilan solishtiriladi: eng
  yaqini 1, eng uzog'i 0. Hamma qiymat teng bo'lsa hammaga 1.0 (bunday
  mezon variantlarni ajratmaydi, jazolashi ham noto'g'ri bo'lardi).
- **Sig'im** — foydalanish ulushi (talab / sig'im). 20 t mashinaga 18 t yuk
  ortish 1 t ortishdan yuqori ball oladi.
- **Smena** — smena reys oynasining qanchasini qoplashi.
- **Malaka** — tugatilgan reyslar × tozalik nisbati (toza / jami).
- **Texnik holat** — uchta ko'paytuvchi: ko'rik enum'i (FIT/LIMITED),
  xizmat rejasi enum'i, va `1/(1+ochiq_remontlar)`.

Uch pog'onali enum'lar (`FIT`/`LIMITED`/`BLOCKED`) teng oraliqqa joylangan —
bu chegara emas, tartibli enum'ning tabiiy raqamli ifodasi.

**Og'irliklar teng** (har biri 1/6). Qaysi mezon muhimroq ekanini bazadagi
hech narsa aytmaydi, shuning uchun `.env` dan sozlanadigan qilib qo'yildi
(`VS_WEIGHT_*`), o'ylab topilgan foizlar yozilmadi.

## Tanlash arifmetika bilan, tahlil LLM bilan

**Ballarni hisob quradi.** Shuning uchun bir xil so'rovga bir xil tartib
chiqadi va har bir ball `criteria[...].detail` orqali qo'lda tekshiriladi.

**LLM yuqori variantlarni birgalikda tahlil qiladi** (`analysis`):
taqqoslaydi, xavfni ko'rsatadi, tavsiya beradi. Bitta chaqiruv — tahlilning
butun ma'nosi variantlarni bir-biri bilan solishtirishda.

LLM ga baholanmagan mezonlar ham ochiq yuboriladi, "sig'imi mos" deb yozib
yubormasligi uchun.

**Tahlil shablonga tushmaydi.** Ollama o'chgan bo'lsa endpoint **503**
qaytaradi va frontend "xatolik yuz berdi, keyinroq urinib ko'ring" deydi.
Uni o'chirish yo'li ham yo'q: `analyze` parametri ham, `VS_LLM_ANALYZE`
sozlamasi ham olib tashlandi.

Har bir juftlikning O'Z `explanation` i esa shablon bilan yoziladi
(`explanation_source`) va LLM ga bog'liq emas.

## Javob tili

**Query parametr**: `?lang=uz|ru|en` (sukut `uz`). Javobdagi **hamma matn**
shu tilda chiqadi — mezon izohi (`criteria[].detail`), kesish sabablari
(`blockers[].text`), juftlik izohi, `summary.criteria_skipped`,
`data_quality.notes` va LLM tahlili. Bazadagi holat kodlari ham tarjima
qilinadi: `IN_MAINTENANCE` -> "texnik xizmatda" / "на техобслуживании" /
"under maintenance".

**Kodlar tarjima qilinmaydi.** `blockers[].code`, mezon nomi (`capacity`,
`distance`, ...), jadval va ustun nomlari uch tilda ham bir xil: ularni
dastur o'qiydi va til o'zgarganda chaqiruvchining kodi buzilmasligi kerak.

Matnlar `texts.py` da, enum nomlari `labels.py` da — ikkalasi ham kalit
bo'yicha, uch til bilan. `labels.py` ni chatbotning YASSI lug'ati bilan
almashtirib bo'lmaydi: bir xil kod har maydonda boshqa ma'no beradi
(`ACTIVE` mashina uchun "faol", xodim uchun "ishda").

## Parametrlar — 12 ta

**Nima kerak** (`transport_type` yoki `route_id` majburiy):

| Parametr | Izoh |
|---|---|
| `transport_type` | `DUMP_TRUCK`, `BUS`, `FLATBED`, … (17 tur). **Bugun ishlaydigan yagona filtr** |
| `driver_category` | A…E. Turdan avtomatik chiqarib bo'lmaydi — pastda |
| `route_id` | Bitta parametr bilan **to'rttasini** to'ldiradi: tur, toifa, reys oynasi, masofa |

**Nima tashiladi:** `cargo_weight_kg`, `cargo_volume_m3`, `passengers`

**Qayerdan/qayerga:** `origin_location_id`, `destination_location_id`

**Qachon:** `on_date` — hujjat, tibbiy ko'rik va bandlik shunga tekshiriladi

**Boshqaruv:** `require_medical` (default `true`), `limit` (10), `lang` (`uz`)

So'rov parametrlari **bazadan ustun turadi**: `cargo_weight_kg` (0/36) va
koordinatalar (0/36) bazada bo'sh, chaqiruvchi ularni qo'lda to'ldira
olishi kerak. Ma'lumot yozila boshlaganda parametrni bermaslik kifoya.

### Nima uchun `driver_category` avtomatik chiqarilmaydi

`route` jadvalidagi haqiqiy juftliklar barqaror emas:

| Transport turi | Talab qilingan toifa |
|---|---|
| `BUS` | D (8/8) ✅ |
| `LONG_LOAD_TRUCK` | C (5/5) ✅ |
| **`PASSENGER_CAR`** | **B:17, D:7, CE:1, E:1, BE:1, A:1** ❌ |
| `FLATBED` | C:5, D:1 ❌ |
| `VAN` | C:2, B:1 ❌ |

Avtomatik chiqarilsa har uchinchi holatda xato bo'lardi.

### Manzil qayerdan yechiladi

`reference_data.catalog_type='LOCATIONS'` — **0 yozuv**, garchi `ddl.sql`
da ruxsat etilgan bo'lsa ham. Butun `reference_data` da (521 yozuv)
koordinata ham yo'q, va `route_point` dagi 44 manzilning **0 tasi**
u yerda topilmaydi.

Shuning uchun manzil **`route_point`** dan yechiladi: 44 ta id, 16 tasida
koordinata. `reference_data.LOCATIONS` to'ldirilganda faqat
`queries.fetch_location` ni o'zgartirish kifoya.

`destination_location_id` bugun **reytingga ta'sir qilmaydi** — javobda
yozib qo'yiladi. Borish masofasi mashina tanlashiga ta'sir qilishi uchun
`fuel_norm` kerak, u esa bo'sh (0 yozuv).

### Chiqarib tashlangan parametrlar

| Parametr | Nega |
|---|---|
| `transport_request_id` | 25 so'rovning hammasida manzil `Navoiyazot` → `Navoiyazot`, yuk ustunlari 0/36 |
| `origin_latitude`/`longitude` | o'rniga `origin_location_id` — dispetcher joy tanlaydi, koordinata emas |
| `window_from`/`window_to` | `driver_shift` da 206 haydovchidan 2 tasida yozuv — soatlik aniqlikni baza ko'tarmaydi. Marshrut berilsa oyna undan olinadi |
| `branch_id`/`department_id` | filtr sifatida so'ralmadi |
| `include_blocked` | kutubxonada qoldi (`ranker.rank`), endpointda yo'q |

## Tuzilishi

```
config.py    og'irliklar, chegaralar, LLM sozlamalari — meyor yo'q
queries.py   bazadan o'qish (faqat SELECT, parametrli)
rules.py     olti mezon + kesish — sof arifmetika, bazasiz sinaladi
ranker.py    orkestrator: kesish -> juftlik -> normalizatsiya -> ball
explain.py   shablon izohi + LLM tahlili
models.py    Pydantic javob sxemasi
router.py    endpoint
```

Nima uchun avval kesish, keyin juftlik: juftliklar soni mashina × haydovchi
bo'lgani uchun tez o'sadi. Bandini oldin chiqarish 127×206 = 26 162 o'rniga
44×12 = 528 juftlik qoldiradi (22.08.2026 o'lchovi, bitta marshrut uchun).

## Sinash

```bash
pytest tests/test_vehicle_selection_rules.py -q     # baza va model kerak emas
python -m atil_ai_dispetcher.vehicle_selection.ranker <route_id>       # bazaga ulanadi
python -m atil_ai_dispetcher.vehicle_selection.ranker --type DUMP_TRUCK --category C
```

## Bugungi baza bilan nima ishlaydi

22.08.2026 o'lchovi:

| Mezon | Holat |
|---|---|
| `skill` | ✅ `driver_license_category` 662 yozuv, `route.required_driver_category` 56/56 |
| `documents` | ⚠️ faqat haydovchi tomoni (`vehicle_document` va `insurance_policy` bo'sh) |
| `technical` | ⚠️ `vehicle_repair` va `current_status` ishlaydi; `vehicle_technical_inspection` 173 yozuvning hammasi `FIT` — ajratmaydi; `maintenance_plan` bo'sh |
| `shift` | ⚠️ `driver_shift` 206 haydovchidan 2 tasida; bandlik `trip`/`waybill` dan ishlaydi |
| `capacity` | ❌ `payload_capacity_kg`, `volume_m3`, `seat_count` — 0/127 |
| `distance` | ❌ `vehicle_telemetry_state`, `vehicle_gps`, `position_log` — bo'sh |

Ikkita bo'sh mezon **kodda bor**: ma'lumot yozila boshlaganda o'zi ishlab
ketadi, kod o'zgarmaydi. Shu paytgacha ular `summary.criteria_skipped` da
ochiq turadi.
