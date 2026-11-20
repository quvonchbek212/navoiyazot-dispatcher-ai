# ATIL backend dasturchilari uchun

## GPS garaj, yaqinlik va kunlik xulosa — 2026-11-04

- `sections.garage` token sozlanganida umumiy API tarixidan hisoblanadi; og‘ir
  arxiv so‘roviga qaytmaydi. Namuna 41.3, 69.24 / 200 m, `is_example=true`.
- `sections.gps_daily` qo‘shildi: kunlik API masofasi yoki kuzatilgan/taxminiy
  masofa, kuzatilgan to‘xtash/harakat va signal uzilishlari. Manba/sifat/davr
  alohida saqlanadi. Frontda bitta kartochka, har transportning sodda javobi.
- `allocation.plan(..., gps_report)` mos transportlarni yangi GPS nuqtasidan
  yuk olish koordinatasigacha to‘g‘ri masofa bo‘yicha tartiblaydi. Bir transport
  bir arizaga tavsiya qilinishi, ustuvorlik va tayyorlik qoidalari saqlangan.
- Koordinata manbalari: `transport_request.origin_latitude/origin_longitude`
  yoki yagona faol `reference_data` / `LOCATIONS` yozuvi (`id` / `location_id`).
  Juftlik yo‘q yoki katalogda zid koordinatalar bo‘lsa yaqinlik noma’lum.
- Jonli 452 arizada kelib chiqish koordinatasi topilmadi; to‘liq tayyor
  transport ham 0. Dasturchilar/mas’ullar ariza nuqtasi va tayyorlik yozuvlarini
  to‘ldirishi kerak. Mashina avtomatik biriktirilmaydi, masofa uydirilmaydi.
- Mavjud `snapshot` / `briefing` va avtomatik jadval ishlatiladi; yangi tab,
  yangi job turi yoki ATIL bazasiga yozish qo‘shilmadi.

Quyidagi qaydlar oldingi bosqichlar holatidir.

## Jonli GPS API Bearer token bilan ulandi — 2026-11-04

Token server `.env` sozlamasidan olinadi. Bo‘sh takroriy token qatori olib
tashlandi; tokenning o‘zi kod, log va hisobotlarga yozilmadi. `current-batch`
jonli DTOsi `entries[].position` ekanligi tasdiqlandi va adapter moslashtirildi.
`accessRevokedVehicleIds` uchun arxiv nuqtasi ham ko‘rsatilmaydi. Tarix API
`POST history-selections` → `GET history-selections/{id}` orqali tekshirildi.
Tafsilot: [GPS_API_INTEGRATION.md](GPS_API_INTEGRATION.md).

Bu ulash bosqichida garaj DB arxivida edi; keyingi bosqich yuqorida berilgan.
WebSocket, alohida masofa va xarita endpointlari ulanmagan. «GPS API
sozlanmagan» yozuvlari tarixiy tekshiruv holatidir.

## Navbatni birgalikda moslash — 2026-11-04

Yangi `sections.allocation` barcha umumiy va kunlik hisoblarda yaratiladi.
Hozirgi oqim: **kutayotgan arizalar → bo‘sh va tekshirilgan transportlar →
takrorlanmaydigan tanlov tavsiyasi → har ariza bo‘yicha sabab → dispetcher qarori**.

- `allocation.py`: ustuvorlikni saqlovchi bipartit moslash. Bir transport bir
  hisobda bir marta ishlatiladi; bir nechta arizaning yuki birlashtirilmaydi.
- `requests()` limiti 200 dan 2000 ga ko‘tarildi. Limit kesilsa `scope_limited`
  va matnli qamrov ogohlantirishi bor. Transportlar ham 2000 bilan chegaralangan.
- `transport_request.binding_vehicle_id` navbatdagi barcha arizalar bo‘yicha
  bandlik tekshiruviga qo‘shildi. Avvaldan transport biriktirilgan ariza qayta
  taqsimlanmaydi. Faqat haydovchisi biriktirilgan arizaga transport tavsiya qilinishi mumkin.
- Har item holati: `RECOMMENDED`, `NEEDS_DATA`, `NO_MATCH`, `SHORTAGE`,
  `ALREADY_BOUND`. `summary` ushbu guruhlarni alohida sanaydi. Manba o‘qilmasa
  `UNAVAILABLE`, raqamlar noma’lum; to‘liq bo‘lmagan qamrovda `PARTIAL`.
- Front kartochkalari: `allocation`, `allocation_matches`, `allocation_waiting`,
  `allocation_scope`. Har ariza matni mahalliy `details` orqali beriladi, modelga
  shaxsiy nomlar/raqamlar yuborilmaydi. «Qolgan arizalar» shu oynada ochiladi.
- Yangi job turi yo‘q: `snapshot` / `briefing` va mavjud avtomatik jadval ishlaydi.
  `selection` eski API mijozlari uchun saqlandi; front undan foydalanmaydi.
- Bu DBga yozmaydigan `REVIEW_ONLY` tavsiya. Kelajak smenasi, vaqt oralig‘idagi
  bandlik, yo‘nalishga yetib borish, haydovchi toifasi hamda real biriktirish
  mavjud backend jarayonida tekshirilishi lozim. Eski tasdiqlash endpointi 410.

Quyidagi sanalangan bo‘limlar oldingi versiyalarning tekshiruv tarixini saqlaydi.

## Mavjud ma’lumot bilan qo‘shilgan beshta funksiya — 2026-11-03

`sections.fleet_state`, `changes`, `repairs`, `waiting_diagnostics`,
`document_coverage` qo‘shildi. Frontda yangi sahifa yo‘q: mavjud narrative
kartochkalari shu natijalardan yaratiladi. Sozlama yoki ATIL DB migratsiyasi kerak emas.

- Transport guruhlari yig‘indisi tekshirilgan transportlar soniga teng. Faol
  reys/yo‘l varaqasidagi yakun belgisi, kelajak jo‘nash yoki bandlik bilan
  ta’mir cheklovi ziddiyat deb ajratiladi. Bu transport nosozligi haqida hukm emas.
- `vehicle_repair.blocks_release` ochiq ta’mirda tayyorlikni to‘sadi. Yopilgan,
  bekor qilingan/rad etilgan ta’mirdagi eski blok belgisi yangi taqiq yaratmaydi.
- Ta’mir: `opened_at`, `estimated_completion_time`, `completed_at`, `status`,
  `vehicle_repair_work_items.completed/description`. Ochiq ta’mirda yakun
  vaqti yoki noto‘g‘ri vaqt tartibi bo‘lsa davomiylik/kechikish chiqarilmaydi.
- Kutish: `transport_head_approved_at`, `submitted_at`, `created_at` manbasi
  matnda farqlanadi; `created_at` navbatga kirish vaqti deb nomlanmaydi.
- Hujjat: `driver_document.kind/s3_url/size_bytes`, `vehicle_document.attachment_id/expiry_date`.
  Fayllar yuklab olinmaydi, maxfiy manzil va hujjat raqamlari LLMga yuborilmaydi.
  Majburiy turlar uchun boshqariladigan talablar manbasi aniqlanmagan; to‘liq
  majburiylik tekshiruvi keyinchalik tasdiqlangan siyosatga bog‘lanishi kerak.
- `change_index` — frontga chiqarilmaydigan, barcha statuslar bo‘yicha ID/status
  va yaratilish vaqtlaridan iborat taqqoslash dalili. Har manba 20 000 yozuv bilan
  chegaralangan. Oldingi kontraktlarda bunday indeks yo‘q bo‘lsa birinchi hisob
  baseline bo‘ladi. Yo‘qolgan ID yakunlangan reys hisoblanmaydi.

18:33 Toshkentdagi jonli tekshiruv: 163 transport (6 ishda, 4 band/rejada,
65 tayyorligi tasdiqlanmagan, 88 zid holat guruhida); 2 ochiq ta’mirda tugash
rejasi yo‘q. 452 navbatdagi arizaning tanlangan 200 tasidan 197 tasida miqdor
yo‘q. 259 haydovchining 249 nafarida har ikki tekshirilgan turdagi fayl qaydi bor.
Bu vaqtga bog‘liq tekshiruv dalili; joriy sonlar keyingi hisobda yangilanadi.
Dalil: `.codex_run/extensions-live-check.json`.

## Yagona AI tahlili oynasi — 2026-11-03

Frontdagi alohida modul sahifalari matnli **AI tahlili** oynasiga birlashtirildi.
Ariza va GPS tekshiruvi javoblari, tarix va sozlamalar shu oynada ochiladi.
Bazaga yangi jadval yoki migratsiya kerak emas; ATIL ma’lumotlari o‘qiladi.

- `GET /ai-dispatcher/api/analysis`: eng so‘nggi hisobning `narrative` matni,
  ariza/transport tanlash uchun `options`, sozlamalar va vazifalar holati.
- `GET /ai-dispatcher/api/jobs/{id}/reading`: tarix yoki bitta tekshiruvning
  matnli javobi. Xom baza qatorlari bu javoblarda yuborilmaydi.
- `narrative.version=1`: `blocks` ichida hisoblangan `text`, AI `explanation`,
  qisqa mahalliy `details`, tavsiya `action`; `priority_ids` ish tartibini beradi.
- `source=llm` faqat AI javobi tekshirilgach qo‘yiladi. Model ishlamasa
  `source=calculated`, `ai_status=UNAVAILABLE`, aniq `notice` va foydali matn qoladi.
- Snapshot ham `analyze` sozlamasiga amal qiladi. Davriy hisobda AI izohi
  avtomatik yaratiladi; eski kunlik izoh yangi hisobga aralashtirilmaydi.
- Garaj sozlamasi o‘zgarsa, yangi hisob tayyor bo‘lguncha oldingi hududning
  xulosasi asosiy tahlildan yashiriladi; tarix o‘zgartirilmaydi.

Mavjud v2 `/dashboard`, job va eksport endpointlari moslik uchun saqlangan.
Eski saqlangan hisobotlar o‘qilganda ulardan hisoblangan matn tuziladi; ularga
model ishlagani haqida yangi da’vo qo‘yilmaydi.

## 2026-11-03 qayta tekshiruv

Baza o‘qilishi va avtomatik worker qayta tekshirildi: yangi snapshot va AI hisoboti
muvaffaqiyatli saqlandi. Ilovaning `/ai-dispatcher/api/health` endpointi HTTP auth
orqali ulanish va worker holatini ko‘rsatadi. Kunlik hisob xatodan keyin bir
yangilash oralig‘i o‘tgach qayta urinadi; oldingi urinishlar tarixda qoladi.

Mahalliy `atil_chatbot/ddl.sql` jonli sxemaga yangilandi; **bazaga migratsiya bajarilmadi**.
Barcha 1026 test o‘tdi. GPS API hali sozlanmagan, garaj koordinatasi namuna,
GPS signallari eskirgan va ayrim garaj tarixlari hajm chegarasida kesilgan.
Bu holatlar natijalarda yashirilmaydi. Batafsil dalil: [VERIFICATION.md](VERIFICATION.md).

## Amaldagi holat: yagona dispetcher v2 — 2026-11-02

Loyiha hozir bor manbalarga moslab soddalashtirildi. Faol oqim:
**Arizalar → bitta ariza uchun tekshiruv → transport/haydovchi holati → reys nazorati → GPS → garaj nazorati → kunlik AI xulosa.**

Ko‘p arizali marshrut optimizatsiyasi, alohida AI Agent/Dispatcher API’lari,
risk/keskin harakat/ETA joblari va bo‘sh telematika manbalariga bog‘langan sahifalar
faol serverdan chiqarildi. Eski joblar qayta bajarilmaydi; tarixiy natijalar saqlanadi.
Yangi asosiy API: `/ai-dispatcher/api/*`; boshqa beshta eski router `main.py`da ham ulanmaydi.

- Birinchi v2 startup sozlamalarni migratsiya qiladi va foydalanuvchi so‘roviga ko‘ra avtomatik jadvalni yoqadi.
- ATILga bevosita yozuv/biriktirish yo‘q. Bitta ariza tekshiruvi `REVIEW_ONLY` natija qaytaradi.
- Bandlik va ko‘rik dalili yetishmasa “tayyor” deb belgilanmaydi. Toifa va qolgan reys talablari dispetcherda qoladi.
- GPS API adapteri qo‘shildi; credential yo‘q bo‘lsa yoki API ishlamasa bazadagi arxivga o‘tiladi.
- Garaj koordinata/radiusi mahalliy sozlamalarda saqlanadi: `PUT /ai-dispatcher/api/garage`.
  Garaj kirish-chiqish va uzoq to‘xtash hisobi mavjud GPS arxiviga tayangan holda qayta ulandi.
  Namuna zona belgilanadi; haqiqiy korxona garaji koordinatasi foydalanuvchi tomonidan tasdiqlanishi kerak.
  Bo‘sh telematika yoki geozona jadvallariga yangi bog‘liqlik qo‘shilmadi.
- Jonli v2 tekshiruv: barcha snapshot bo‘limlari o‘qildi, bitta ariza va GPS tarixi tekshirildi;
  LLM xulosasi `COMPLETE` qaytdi. Dalil: `.codex_run/dispatch_v2_smoke.json`.

[Hozirgi loyiha qo‘llanmasi](README.md) · [GPS API sozlash va kontrakt](GPS_API_INTEGRATION.md).

**Quyidagi v1 bo‘limlari oldingi tahlil va integratsiya tarixi sifatida saqlangan;
ular faol v2 funksiyalari ro‘yxati emas.**

## Yangi xavfsizlik va ETA moduli — 2026-11-02

Kod va UI qo‘shildi: [intelligence/README.md](intelligence/README.md).
Yangi DB jadvali yoki migratsiya bajarilmadi; barcha ATIL so‘rovlari `READ ONLY`.

2026-11-02 **11:28 Toshkent** vaqtidagi cheklangan tekshiruv:

- Bir GPS transportining oxirgi soatida 2 ta nuqta, oraliq **1 134 soniya**.
  Manba o‘qildi, lekin risk va keskin harakatlar uchun qamrov yetmadi.
  Bu natijani barcha transportlarga umumlashtirmang.
- ETA uchun dastlabki **500 faol/rejadagi reys**, **3 054 tarixiy reys** o‘qildi.
  Faol reyslar ro‘yxati limit bilan kesilgan. **ETA berilgan reys: 0**.
- 234 reysda faol status bilan `actual_arrival_at` yoki `release_return_instant` birga bor;
  168 tasida tanlangan mezonlarga mos, o‘tgan safar vaqtidan uzun tarix yetmadi;
  63 tasida eski jo‘nash vaqtining zonasi tasdiqlanmagan;
  qolgan 35 tasida foydalanishga yaroqli jo‘nash vaqti yo‘q.
- Reja vaqti o‘tgan 190 yozuv ajratildi. Bu **kelajak prognozi emas**;
  UI buni `OVERDUE` deb alohida ko‘rsatadi. Yakunlanganlik ziddiyati bo‘lgan
  yozuvlardan kechikish ogohlantirishi chiqarilmaydi.

Dasturchilar bilan quyidagi kontraktlar aniqlashtirilsin:

| Manba / ustun | Kerakli tuzatish yoki tasdiq | Ta’siri |
|---|---|---|
| `gps_archive_point.fix_time`, `payload.speed`, `valid`, `course`; `vehicle_gps.provider_connection` | Birliklar va GPS haqiqiyligini saqlash; keskin harakat uchun ≤2 s chastota yoki keyinchalik alohida tasdiqlangan qurilma-hodisa manbasi. `course` gradusda bo‘lsin. | Tezlik, tormoz, tezlanish, burilish dalili |
| `waybill.vehicle_id`, `driver_id`, `actual_departure_at`, `actual_return_at`; `trip.release_departure_instant`, `release_return_instant` | Haydovchi biriktirish vaqtini to‘liq va ziddiyatsiz saqlash; yopilgan yozuvlarni ochiq qoldirmaslik | Hodisani to‘g‘ri haydovchiga bog‘lash |
| `trip.status`, `actual_arrival_at`, `release_return_instant` | Faol/yakunlangan holatni bir-biriga mos qilish; qaytish va yetib kelish ma’nolarini ajratish | Soxta ETA va kechikish xabarini to‘sish |
| `trip.actual_departure_at`, `actual_arrival_at`, `scheduled_*` va zonali `planning_*_instant`, `release_departure_instant` | Eski ikki actual vaqt bir konvensiyada yozilganini tasdiqlash; UTC/Toshkent farqini backfill va yangi yozuvlarda bir xil qilish. Yetib kelish uchun kelgusida aniq zonali ustun taqdim etish. | Tarixiy davomiylik va joriy ETA |
| `trip.route_id`, `transport_request_id`, `work_mode`; `transport_request.origin_location_id`, `destination_location_id`, `work_mode`, `trip_type`; `transport_vehicle.transport_type` | Haqiqiy mos tarixiy reyslarni guruhlash uchun ID va ish rejimini to‘ldirish. Nom yoki toifani taxminiy uydirmaslik. | Yetarli taqqoslanadigan ETA tarixi |
| Yo‘l kesimi bo‘yicha tezlik limiti | Hozir UIga korxona chegarasi kiritiladi. Qonuniy yo‘l limiti kerak bo‘lsa segment/geozona, amal qilish vaqti va transport turini qamrab olgan tasdiqlangan manba bering. | Korxona chegarasi bilan qonuniy qoidabuzarlikni aralashtirmaslik |

Dalil: `.codex_run/intelligence_smoke.json`. Nuqsonlar avtomatik tuzatilmadi.
Xabarlar faqat shu ilovaning lokal markazida; tashqi xabar yuborilmaydi.

Qo‘shimcha regressiya topilmasi: `tests/test_sql_catalog.py::test_ddl_fayli_bazadan_orqada_qolmagan`
jonli bazaga ulanishda ham o‘tmadi — `atil_chatbot/ddl.sql`dagi sxema bazadan orqada.
18 ta SQL katalog so‘rovi bazada muvaffaqiyatli bajarildi. Ushbu sxema faylini
backend bilan kelishib alohida yangilash kerak; yangi modul bu faylga tayanmaydi.

## Hozirgi bajarish chegarasi

Unified UI `POST /ai-dispatcher/api/jobs/{id}/decision` orqali mahalliy
tasdiq/rad etishni qayd qiladi. Hech qanday ATIL yozuvi yoki tashqi xabar
yuborilmaydi. `NOT_SENT` bajarilmagan holatidir, muvaffaqiyatli assignment emas.

Mavjud ATIL sxemasida `transport_planning_operation`,
`transport_planning_decision_claim`, `transport_assignment_command`,
`transport_assignment_event`, `transport_assignment_change_outbox` bor.
Integratsiya shu operatsiyalarning egasi bo‘lgan API orqali qurilsin.
Ularning yozish kontrakti AI kodidan taxmin qilinmagan.

## Kelishilishi kerak bo‘lgan API kontrakti

Backend endpointi, autentifikatsiyasi va ruxsatlari ma’lum bo‘lgach adapter
qo‘shiladi. Tavsiya etiladigan kirish:

```json
{
  "operation_id": "unique-approval-operation-id",
  "proposal_id": "saved-dispatch-job-id",
  "actor_id": "ATIL-authenticated-user-id",
  "expected_request_versions": {"request-uuid": 3},
  "assignments": [{
    "vehicle_id": "vehicle-uuid",
    "driver_id": "driver-uuid",
    "request_ids": ["request-uuid"],
    "stops": [],
    "starts_at": "2026-11-02T08:00:00+05:00",
    "ends_at": "2026-11-02T10:00:00+05:00"
  }]
}
```

Backend bitta tranzaksiyada ruxsat, versiya, ariza statusi, transport va
haydovchining vaqt bo‘yicha bandligi, hujjatlar, tibbiy/texnik ko‘rik,
sig‘im va boshqa qattiq cheklovlarni qayta tekshiradi. Bir xil operation_id
bir xil natijani qaytarsin; boshqa payload bilan qayta ishlatish `409` bo‘lsin.

Javobda `accepted`, `applied`, `conflict`, `rejected` alohida bo‘lsin.
HTTP 200 yoki webhook qabul qilinishi “bajarildi” deb olinmasin. Haqiqiy
trip/assignment ID, backend revision va bajarish vaqti qaytsin.
Noaniq timeout holatida operation_id orqali natijani tekshirish endpointi
kerak. Outbox yetkazish va qayta urinish uchun ishlatilishi mumkin.

## Ma’lumot bo‘yicha aniq topshiriqlar

2026-11-01 tekshiruvi (jonli holat o‘zgaradi; UI dagi JSON eksport qayta o‘lchaydi):

| Jadval / ustun | Kuzatilgan holat | Kerakli tuzatish |
|---|---|---|
| transport_vehicle.payload_capacity_kg / cargo_capacity_tons | 161 transportda bo‘sh | Tegishli yuk transportlari uchun sig‘im, birlik va manbani to‘ldirish |
| transport_vehicle.volume_m3 / seat_count / passenger_capacity | Asosiy sig‘im ustunlari bo‘sh, passenger_capacity faqat 1 yozuvda | Transport turi bo‘yicha majburiy sig‘im qoidasi |
| transport_request origin/destination latitude/longitude | 2795 arizada bevosita koordinatalar bo‘sh | Nuqta/manzil katalogi bilan barqaror bog‘lash |
| transport_request_point.latitude/longitude | 192 nuqtadan 2 tasi, 1 ariza | Yuklash va tushirish nuqtalarini geokodlash/tasdiqlash |
| reference_data LOCATIONS / BRANCHES | 6 manzildan 3 koordinatali; 4 filialda koordinata yo‘q | Garaj/filial koordinatasi va mas’ul egasini belgilash |
| vehicle_telemetry_state | Bo‘sh | GPS arxividan tekshirilgan joriy holatni yangilash; speed birligi va event vaqti |
| vehicle_gps | 70 faol tekshirilgan bog‘lanish | Mapping bilan signal yangiligini alohida kuzatish |
| driver_shift | 6 yozuv | Reja kunlariga smena, vaqt zonasi va haydovchi qamrovi |
| vehicle_document / insurance_policy | 1 / 0 yozuv | Hujjatlarni transportga bog‘lash va haqiqiylik sanalarini to‘ldirish |
| trip.driver_id / transport_request_id | 4 / 10 bog‘lanish mos yozuv topmadi | Arxivlash/soft-delete va tarixiy bog‘lanish kontraktini aniqlash |

Jonli yangi ilova sinovida 200 arizalik reja: 199 `NO_COORDINATES`,
1 `NO_VEHICLE_LEFT`; birorta marshrut tayinlanmadi. Bu jami navbat emas,
optimizatorning 200 arizalik tekshiruv limiti.

Yangi `planning_start_instant` / `planning_end_instant` ustunlari bor.
AI adapterlari ularni ustun qo‘yib, eski timestamp qiymatiga fallback qiladi.
Eski zonasiz timestamp uchun Asia/Tashkent qabul qilinadi. Backend haqiqiy
biznes vaqt zonasi boshqa bo‘lsa bu mapping alohida kelishilsin.

## GPS unumdorligi

`gps_archive_point` bo‘yicha global eng oxirgi vaqtni qidirish 15 soniyalik
audit limitiga urilgan. Bu signal yo‘q degani emas. Dashboard global GPS
arxivini skan qilmaydi. Backendda mavjud indekslar va query plan tekshirilib,
vehicle/binding + fix_time bo‘yicha diapazon o‘qish yo‘li tasdiqlansin.
Indeks yaratish AI tomonidan bajarilmagan.

## Hozirgi cheklovlar

- Bu bir hostdagi dispetcher ilovasi; ko‘p host uchun umumiy queue/storage kerak.
- Auth hozir loyihaning bitta HTTP Basic hisobidir; ATIL foydalanuvchi/rol/filial
  ruxsatlari backend SSO kontrakti bilan qo‘shilishi kerak.
- GPSning jonli xarita kartografiyasi va ATIL event webhook ingress hali yo‘q.
  Mavjud monitor koordinata va signal dalillari bilan hisobot beradi.
- Baza ma’lumoti yo‘q bo‘lsa marshrut yoki tayyorlik sun’iy yaratilmaydi.
- “Reja tejalishi” alohida tashish modeliga nisbatan matematik farq; real
  iqtisodiy foyda uchun amalga oshgan reys/yoqilg‘i/xarajat bilan o‘lchov kerak.
