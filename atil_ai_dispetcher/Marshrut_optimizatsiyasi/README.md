# Marshrut optimizatsiyasi (VRP)

Bir kunlik arizalarni mashinalarga taqsimlaydi va **borish tartibini** tuzadi.

```
POST /route-optimization/plan
```

**Bitta endpoint, ikki rejim.** Rejimni `stops` maydoni belgilaydi:

```jsonc
{}                                    // bazadagi bugungi arizalar
{"depot_latitude": 40.08, ...}        // xuddi shu, sozlamalar bilan
{"stops": [...], "vehicles": [...]}   // berilgan nuqtalar, bazaga tegilmaydi
```

POST — chunki nuqtalar ro'yxati query-string'ga sig'maydi. Tana to'liq
ixtiyoriy: `{}` yuborilsa ham ishlaydi.

## Masala nima

Har bir ariza — **A nuqtadan B nuqtaga** yuk. Bu klassik "omborchidan
mijozlarga tarqatish" (CVRP) emas: har arizada **ikki to'xtash** bor va ular
bitta mashinada, **yuklash avval** bo'lishi shart. Masala turi — **PDPTW**
(Pickup and Delivery Problem with Time Windows).

Hisobga olinadigan cheklovlar:

| Cheklov | Manba |
|---|---|
| yuk sig'adimi (kg va m3) | `transport_vehicle.payload_capacity_kg`, `volume_m3` |
| transport turi mos keladimi | `transport_request.required_transport_type` |
| vaqt oynasiga ulguradimi | `transport_request.planned_departure_at` / `planned_arrival_at` |
| smena chegarasidan oshmaydimi | `driver_shift.planned_hours`, `planned_end_at` |
| mashina bo'shmi | `trip`, `waybill` — **reja oynasi bilan kesishishiga qarab** |
| bloklovchi remont yo'qmi | `vehicle_repair.blocks_release` |
| xavfli yuk talabi | `shipment` -> `hazard_profile` — **avtomatik** |
| dispetcher biriktirgan mashina | `transport_request.binding_vehicle_id` — **buzilmaydi** |
| chiqish nuqtasi | `vehicle_telemetry_state` -> `reference_data` (BRANCHES) -> so'rov |
| dock navbati | `dock_slot` — **ogohlantirish**, qattiq cheklov emas |

## Uchta qoida — modulning butun mantig'i shu

### 1. Raqamlar bazadan O'LCHANADI, o'ylab topilmaydi

Marshrut optimizatsiyasi odatda uchta qattiq yozilgan raqamga tayanadi:
"to'g'ri chiziqni 1.3 ga ko'paytiramiz", "60 km/soat deb olamiz", "yuklash
30 daqiqa". Bu modulda ularning uchtasi ham ATIL ning **o'z ma'lumotidan**
o'lchanadi (`calibration.py`):

| Parametr | Qayerdan o'lchanadi |
|---|---|
| yo'l koeffitsienti | `route_point`: bazadagi yo'l masofasi / to'g'ri chiziq |
| o'rtacha tezlik | `route_point`: masofa / `drive_duration_from_previous_minutes` (yetmasa `trip`) |
| xizmat vaqti | `trip_event`: "yetib bordi" -> "yukladi/tushirdi" |

**Mediana olinadi, o'rtacha emas** — bitta xato yozuv (3 daqiqada 5000 km)
o'rtachani buzadi, medianani deyarli buzmaydi.

O'lchov yetmasa (`RO_MIN_CALIBRATION_SAMPLES` dan kam) qiymat **noma'lum**
bo'lib qoladi. Har bir qiymat yonida javobda uning **manbasi** va **o'lchov
soni** turadi:

```json
"calibration": {
  "average_speed_kph": 4.5,
  "speed_source": "trip",
  "speed_samples": 25,
  "road_factor": 1.0,
  "road_factor_source": "straight_line",
  "time_aware": true
}
```

### 1a. Har bir qiymat uchun MANBA ZANJIRI bor

Modul bitta ustunga bog'lanib qolmaydi. Har bir kerakli qiymat uchun
aniqdan taxminiyga qarab tartib belgilangan — qaysi biri to'lgan bo'lsa,
o'sha ishlatiladi. **Ma'lumot bazaga tushgani sari modul o'zi aniqroq
ishlay boshlaydi, kod o'zgarmaydi.**

| Nima kerak | 1-manba | 2-manba | 3-manba | 4-manba |
|---|---|---|---|---|
| Nuqta koordinatasi | `*_point.latitude` | `transport_request.origin_latitude` | `reference_data` (LOCATIONS) | `route_point` |
| Mashina chiqish nuqtasi | `vehicle_telemetry_state` | `reference_data` (BRANCHES) | so'rovdagi `depot_*` | — |
| Yuk og'irligi | `transport_request.cargo_weight_kg` | `shipment.cargo_weight_kg` | `shipment.weight_tons` x1000 | `null` |
| Yuklash oynasi | `*_point.planned_departure_at` | `transport_request.planned_departure_at` | `shipment.ready_at` | `shipment.scheduled_pickup_at` |
| Yetkazish muddati | `*_point.planned_arrival_at` | `transport_request.planned_arrival_at` | `shipment.requested_delivery_at` | `shipment.scheduled_delivery_at` |
| O'rtacha tezlik | `trip` (haqiqiy) | `route_point` (reja) | `.env` | `null` |
| Yo'l koeffitsienti | `route_point` o'lchovi | `.env` | 1.0 (to'g'ri chiziq) | — |

Oxirgi ustun `null` bo'lsa — o'sha cheklov **tekshirilmadi** deb yoziladi,
"muammo yo'q" deb emas.

### 2. `null` — nol emas

Tezlik noma'lum bo'lsa **vaqt umuman hisoblanmaydi**: `duration_minutes`
`null` bo'ladi, vaqt oynasi va smena **tekshirilmaydi**, maqsad avtomatik
`distance` ga tushadi. Bu javobda `calibration.time_aware=false` bilan ochiq
ko'rsatiladi.

Sig'imi ko'rsatilmagan mashinaga sig'im cheklovi **qo'llanmaydi** — u
"sig'imi yetmaydi" deb chiqarib tashlanmaydi. (25.08.2026 da
`payload_capacity_kg` 128 mashinaning 128 tasida ham bo'sh.)

### 3. Joylanmagan ariza jimgina yo'qolmaydi

Har bir joylanmagan ariza `unassigned` da **sababi bilan** qaytadi:

| Kod | Ma'nosi |
|---|---|
| `NO_COORDINATES` | nuqtaning koordinatasi yo'q, masofa hisoblanmaydi |
| `NO_MATCHING_VEHICLE` | talab qilingan turda bo'sh mashina yo'q |
| `CAPACITY` | hech bir mashinaning sig'imi yetmadi |
| `TIME_WINDOW` | vaqt oynasiga ulgurib bo'lmaydi |
| `SHIFT_LIMIT` | smena/reys davomiyligidan oshadi |
| `HAZARD` | xavfli yuk talabiga mos mashina yo'q |
| `NO_VEHICLE_LEFT` | bo'sh mashina qolmadi |

"Reja tayyor" deb 40 tadan 12 tasini ko'rsatish — eng qimmat xato.

## Algoritm

```
1. QURISH        har arizani eng arzon joyga qo'yish
                 (barcha mashina x barcha o'rin juftligi)
2. KO'CHIRISH    arizani boshqa mashinaga/o'ringa o'tkazib ko'rish
3. ALMASHTIRISH  ikki mashinadagi ikki arizani almashtirish
```

Har bir yurish faqat **narxni kamaytirsa** qabul qilinadi. Tasodifiy son
ishlatilmaydi — **bir xil so'rovga bir xil reja** chiqadi.

Narx bitta o'lchov birligida hisoblanadi: vaqt ma'lum bo'lsa **daqiqada**
(masofa ham kalibrlangan tezlik orqali daqiqaga aylantiriladi), aks holda
**kilometrda**. Kilometr bilan daqiqani qo'shib yuborish — bu masalada eng
keng tarqalgan xato.

**Vaqt byudjeti** (`RO_TIME_BUDGET_SECONDS`, sukut 5 s) tugasa yaxshilash
to'xtaydi va o'sha paytdagi eng yaxshi yechim qaytadi. Yechim har doim to'liq
va yaroqli; byudjet urilgani `summary.time_budget_hit` da ko'rinadi.

**Nima uchun OR-Tools emas:** serverga yangi og'ir bog'liqlik qo'shilmadi,
modul faqat standart Python bilan ishlaydi. Hajm o'sib ketsa
`solver._best_insertion` ni almashtirish yetarli — qolgan kod tegilmaydi.

## Foyda qanday o'lchanadi

`summary.baseline_distance_km` — **optimizatsiyasiz** variant: har arizani
alohida mashinada tashish (chiqish -> yuklash -> tushirish -> qaytish).
Dispetcher qo'lda ishlaganda amalda shunday bo'ladi.

`saved_percent` — reja shunga nisbatan qancha qisqartirgani. Solishtirish
bazasi bo'lmasa "23% tejaldi" degan gap ham bo'lmaydi.

## Bugungi baza holati (25.08.2026)

| Manba | Holat | Ta'siri |
|---|---|---|
| `transport_request` koordinatalari | 55 dan **0** ta | bazadan reja tuzib bo'lmaydi |
| `transport_request_point` | **0** qator | nuqta darajasidagi oyna yo'q |
| `vehicle_telemetry_state` | **0** qator | mashina qayerdaligi noma'lum -> garaj kerak |
| `route_point` koordinatasi + masofasi | 114 dan **0** juftlik | yo'l koeffitsienti o'lchanmaydi |
| `trip` (tugagan) | 33 ta | tezlik o'lchanadi, lekin **4.5 km/soat** chiqyapti |
| `dock_slot`, `hazard_profile`, `tariff` | 0 / 0 / 1 | bu cheklovlar qo'llanmaydi |

O'lchangan **4.5 km/soat** — bu modulning xatosi emas, bazadagi holat:
`trip.actual_distance_km` kichik, davomiyligi esa o'rtacha 11 soat. Ya'ni
yo tugash vaqti kech yozilyapti, yo masofa to'liq yozilmayapti. Shu tuzalguncha
tezlikni so'rovda berish kerak (`average_speed_kph`).

**Shuning uchun `stops` rejimi bor.** Nuqtalar va mashinalar so'rovning
o'zida keladi, bazaga umuman murojaat qilinmaydi — modul **bugun ham
to'liq ishlaydi**:

```bash
curl -u user:pass -X POST http://localhost:8000/route-optimization/plan \
  -H "Content-Type: application/json" -d '{
    "stops": [
      {"id":"A1","number":"TR-1001",
       "pickup_latitude":40.0844,"pickup_longitude":65.3792,
       "dropoff_latitude":39.6542,"dropoff_longitude":66.9597,
       "weight_kg":12000},
      {"id":"A2","number":"TR-1002",
       "pickup_latitude":40.1000,"pickup_longitude":65.3700,
       "dropoff_latitude":39.8994,"dropoff_longitude":66.2500,
       "weight_kg":8000}
    ],
    "vehicles": [
      {"id":"V1","plate_number":"85896SAA","capacity_kg":25000,
       "start_latitude":40.0844,"start_longitude":65.3792}
    ],
    "average_speed_kph": 55,
    "road_factor": 1.25
  }'
```

## Baza to'lganda nima o'zgaradi

**Hech narsa — kod o'zgarmaydi.** Modul ma'lumot paydo bo'lishi bilan o'zi
aniqroq ishlay boshlaydi:

1. `transport_request.origin_latitude/longitude` to'lsa — `stops`siz rejim ishlaydi;
2. `route_point` da masofa + koordinata juftliklari 10 tadan oshsa — yo'l
   koeffitsienti o'lchanadi va to'g'ri chiziq o'rniga haqiqiy nisbat ishlatiladi;
3. `trip` tarixi to'g'rilansa — tezlik haqiqiy reyslardan olinadi;
4. `trip_event` to'lsa — yuklash/tushirish vaqti jadvalga qo'shiladi;
5. `vehicle_telemetry_state` ishlasa — mashina garajdan emas, **turgan
   joyidan** hisoblanadi;
6. `reference_data` (LOCATIONS) to'lsa — manzil katalogi ishlaydi, `route_point`
   ga tayanish kerak bo'lmaydi;
7. `reference_data` (BRANCHES) to'lsa — har mashina **o'z filialidan** chiqadi,
   `depot_latitude` berish kerak bo'lmaydi;
8. `transport_request.wms_shipment_id` bog'lansa — og'irlik, muddat va **xavfli
   yuk** avtomatik keladi;
9. `RO_OSRM_URL` berilsa — to'g'ri chiziq o'rniga **haqiqiy yo'l masofasi**.

## Fayllar

| Fayl | Vazifasi |
|---|---|
| `config.py` | `.env` sozlamalari, cheklovlar |
| `models.py` | javob sxemasi (Swagger shundan chiziladi) |
| `queries.py` | faqat `SELECT`, READ ONLY tranzaksiyada |
| `calibration.py` | bazadan o'lchanadigan parametrlar |
| `geo.py` | masofa matritsasi (haversine yoki OSRM) |
| `solver.py` | VRP yadrosi — algoritm faqat shu yerda |
| `optimizer.py` | orkestratsiya, javob yig'ish |
| `explain.py` | shablon izohi + LLM tahlili |
| `router.py` | FastAPI endpointi (bitta) |

Testlar: `tests/test_route_optimization.py` (baza va model kerak emas).

## LLM ning roli

**Rejaga tegmaydi.** Reja arifmetika bilan tuziladi — shuning uchun uni
qo'lda tekshirish mumkin va bir xil so'rovga bir xil javob chiqadi.

LLM tayyor rejani **tushuntiradi**: nechta mashina ishlatildi, qaysi
marshrut eng og'ir, qayerda xavf bor, nima tekshirilmagan.

**Tahlil shablonga tushmaydi.** LLM javob bermasa endpoint **503**
qaytaradi va frontend "xatolik yuz berdi, keyinroq urinib ko'ring" deydi.
Sababi — bu loyihada tahlilning o'zi mahsulot: shablon matni "AI tahlil
qildi" degan yolg'on taassurot berardi. Tahlilni o'chirish yo'li ham yo'q:
`analyze` maydoni ham, `RO_LLM_ANALYZE` sozlamasi ham olib tashlandi
(LLM javobni ~10 soniyaga cho'zadi, reja o'zgarmaydi).

## Javob tili

**Query parametr**: `?lang=uz|ru|en` (sukut `uz`). Tanada emas — Swagger uni `Parameters` bo'limida ro'yxat qilib ko'rsatadi va tilni tanani ochmasdan tanlash mumkin. Javobdagi **hamma matn** shu
tilda chiqadi — joylanmagan ariza sababi, transport turining nomi,
`data_quality.notes`, `requirements` dagi tushuntirish, marshrut izohi va
LLM tahlili.

```
POST /route-optimization/plan?lang=ru
```

```jsonc
// uz
{"required_transport_type": "havo platformasi",
 "reason": "Yuklash yoki tushirish nuqtasining koordinatasi yo'q — ..."}
// ru
{"required_transport_type": "автовышка",
 "reason": "Нет координат пункта погрузки или разгрузки — ..."}
// en
{"required_transport_type": "aerial platform",
 "reason": "The pickup or delivery point has no coordinates — ..."}
```

**Kodlar tarjima qilinmaydi.** `reason_code`, `need`, `kind`, jadval va
ustun nomlari uch tilda ham bir xil: ularni dastur o'qiydi, til
o'zgarganda chaqiruvchining filtri buzilmasligi kerak.

Matnlar `texts.py` da bitta joyda, kalit bo'yicha turadi. Transport
turlarining nomi u yerda takrorlanmaydi — `atil_chatbot/core/lang.py`
dagi chatbot lug'atidan olinadi, ya'ni prompt va API bir xil so'zni
ishlatadi. Sxemaga yangi tur qo'shilsa va tarjimasi bo'lmasa **kodning
o'zi** qaytadi: tarjima o'ylab topilmaydi.

## So'rov maydonlari

| Maydon | Rejim | Izoh |
|---|---|---|
| `on_date` | bazadan | reja sanasi, sukut — bugun |
| `request_ids` | bazadan | aniq arizalar (berilsa holat filtri o'chadi) |
| `window_from` / `window_to` | bazadan | reja oynasi — bandlik shunga qarab hisoblanadi. Sukut: `on_date` ning butun kuni |
| `depot_latitude` / `depot_longitude` | bazadan | garaj — ZAXIRA. Avval telematika, keyin filial koordinatasi ishlatiladi |
| `objective` | ikkalasi | `distance` / `duration` / `balanced` |
| `respect_time_windows` | ikkalasi | oyna qattiqmi |
| `average_speed_kph` | ikkalasi | berilmasa bazadan o'lchanadi |
| `stops` / `vehicles` | qo'lda | berilsa bazaga murojaat yo'q |
| `road_factor` | qo'lda | to'g'ri chiziq -> yo'l koeffitsienti |

Endpointdan chiqarilgan, lekin `optimizer.plan_from_database()` da qolgan
parametrlar: `statuses`, `vehicle_ids`, `depot_location_id`,
`service_minutes`, `respect_capacity`. Sabablari `router.py` boshida
yozilgan.

`hazard_un_number` butunlay olib tashlandi: xavflilik endi bazadan
avtomatik aniqlanadi (`wms_shipment_id` -> `shipment` -> `hazard_profile`).
Xavflilik butun so'rovga emas, ayrim arizaga tegishli xususiyat.
