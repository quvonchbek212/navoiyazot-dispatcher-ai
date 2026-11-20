# Garaj va avtopark monitoringi

Bitta public endpoint: **`POST /fleet-yard/monitor`**. Oldingi `/readiness`,
`/zones`, `/evaluate`, `/visits`, `/utilization` marshrutlari ilovaga ulanmaydi.
Autorizatsiya: mavjud HTTP Basic (`API_USERNAME`, `API_PASSWORD`).

## So'rov

```json
{
  "garage": {
    "name": "Garaj",
    "latitude": 41.3,
    "longitude": 69.24,
    "radius_meters": 200
  },
  "plate_number": null,
  "days": 60,
  "analyze": true
}
```

Koordinatalar namuna; haqiqiy garajga almashtiring. Nom sukut bo'yicha
`Garaj`, radius 200 metr. `plate_number` yo'q, `null` yoki bo'sh bo'lsa barcha
transportlar olinadi. Raqam berilsa uning harflari katta-kichikligi va ajratuvchi
belgilari normallashtiriladi: `10 A 123 A` va `10A123A` bir xil. UUID parametr
qabul qilinmaydi. Raqam topilmasa 404, bir nechta kartochkada takrorlansa 409.

`days` faqat 1/7/15/30/60: 1 kun, 1 hafta, 15 kun, 1 oy, 2 oy.
Standart qiymat 60; tanlangan davrgacha bo'lgan kesimlar birga qaytadi.
Masalan, 15 tanlansa 1/7/15, 60 tanlansa barcha beshta kesim qaytadi.
Oylar qat'iy davomiylik: 1 oy = 30 kun, 2 oy = 60 kun.
Ixtiyoriy `as_of` vaqt zonasi bilan beriladi;
berilmasa hozirgi Toshkent vaqti. Kelajak vaqti rad qilinadi.
To'liq namuna: [example_request.json](example_request.json).

## Javob

- `summary`: butun tanlangan flotning hisobot vaqtidagi holatlari,
  garajda to'xtagan/harakatdagi/tashqarida to'xtagan/sekin yurayotgan sonlar,
  eskirgan signal, noma'lum holatlar va faol ogohlantirishlar.
- `vehicles`: transport raqami, oxirgi GPS, tezlik, garajga kirish-chiqish,
  tashriflar, kuzatilgan harakatsiz vaqt va davrlar bo'yicha faollik.
- `periods`: harakat yoki garajda turish kuzatilgan transportlar ro'yxati,
  reys/yo'l varaqasida ish qayd etilgan transportlar, 1 kun / 1 hafta / 15 kun / 1 oy / 2 oy kesimlarda.
- `alerts`: uzoq tashqi to'xtash, ehtimoliy tirbandlik, GPS uzilishi,
  bog'lanish yoki ma'lumot yetishmasligi. Bu so'rovning javobidir; fon
  xabarchisi yoki tashqi jo'natma ishga tushmaydi.
- `analysis`: barcha tanlangan transportlar uchun umumiy AI xulosasi,
  dalil identifikatorlari, topilmalar va amaliy tavsiyalar.
- `data_quality`: manbalar, qator limitlari, kuzatuv va talqin cheklovlari.

## Hisobning ma'nosi

Garajga kirish-chiqish avvalgi geofence dvigatelida gisterezis va ketma-ket
nuqtalar bilan tasdiqlanadi. Birinchi ichki nuqta kirish vaqtini isbotlamaydi.
GPS bo'shlig'i va oxirgi nuqtadan hozirgacha bo'lgan vaqt turishga qo'shilmaydi.
`observed_*` davomiyliklar nuqtalar orasidagi kuzatuvdan baholanadi; fizik
harakatning uzluksiz yozuvi deb talqin qilinmaydi.

Tezlik noma'lum bo'lsa nolga almashtirilmaydi. `position_log.speed` birligi
tasdiqlanmagani uchun undan km/soat yasalmaydi. Aynan bir vaqtdagi manbalar
qarama-qarshi bo'lsa nuqtalar chiqariladi. Mos nusxalar birlashtiriladi.
Fizik jihatdan imkonsiz GPS sakrashi (400 km/soatdan yuqori koordinata farqi)
hodisa yaratish uchun ishlatilmaydi. Past tezlikli ikki nuqta joyi siljigan
bo'lsa ular orasidagi vaqt uzluksiz to'xtash deb olinmaydi; transport oraliqda
yurib qayta to'xtagan bo'lishi mumkin.

GPSsiz yoki eskirgan signal bilan joriy holat noma'lum. Umuman tasdiqlangan
harakat/to'xtash bo'lmasa tegishli jami `null`; noma'lumlar tasdiqlangan sonlarga
qo'shilmaydi. Ayrim transportlar noma'lum bo'lsa sonlar kuzatilgan minimumdir.
`NO_GPS_DATA` oldin signal bo'lganini isbotlamaydi: u `GPS_SIGNAL_LOST` bilan
almashtirilmaydi. Faqat garajda kuzatilganlik butun davr garajda turganlik emas.

Reys va yo'l varaqasi `trip_id` bo'yicha takror sanalmaydi. Sana xatoli
hujjatlar chiqariladi va sabablar qaytariladi. Hujjat faolligi GPS joylashuvi
bilan alohida ko'rsatiladi. Qisman o'lchov to'liq kilometr/motosaat jami emas.

Garajdan tashqaridagi nuqta yo'l ekanligi xarita bilan tekshirilmagan.
Sekin yurish tirbandlik ehtimoli, isbotlangan sabab emas. Xarita, yo'l
vaziyati, topshiriq va dispetcher tasdig'i alohida talab qilinadi.

## Ogohlantirish chegaralari

`policy` ichida sozlanadigan **sinov qiymatlari**, korxona me'yorlari emas:

| Maydon | Sukut qiymati |
|---|---:|
| `stationary_speed_kph` | 1 km/soat |
| `long_stop_minutes` | 15 daqiqa |
| `slow_speed_kph` | 10 km/soat |
| `slow_duration_minutes` | 10 daqiqa |
| `signal_timeout_seconds` | 300 soniya |
| `max_gap_seconds` | 300 soniya |
| `hysteresis_meters` | 30 metr |
| `stationary_radius_meters` | 50 metr |
| `confirmation_points` | 2 |
| `confirmation_seconds` | 30 soniya |

## AI

Hisob va transport kuzatuvlarini kod tuzadi. Model butun flotning hisoblangan
sonlari, davrlar va ogohlantirish guruhlarini izohlaydi; har transport bo'yicha
alohida model ishlagan deb ko'rsatilmaydi. Raqam, davlat raqami, koordinata va
UUID model matniga qo'shilmaydi. Har topilma/tavsiyaning kodi va dalil havolasi
tekshiriladi. Bunday tekshiruv erkin matnning har jumlasini matematik isbotlamaydi.

`analyze=false`: `analysis.status=DISABLED`, hisob saqlanadi.
Model yoki tekshiruv xatosi: HTTP 200 bilan hisoblangan natijalar va
`analysis.status=UNAVAILABLE`, ochiq ogohlantirish. Bu matn model javobi deb
ko'rsatilmaydi. Muvaffaqiyatli model javobi `source=llm`, `status=COMPLETE`.

## Frontend va ishga tushirish

```powershell
.\venv\Scripts\python.exe -m uvicorn atil_ai_dispetcher.fleet_yard_llm.web:app --host 127.0.0.1 --port 8010
```

http://127.0.0.1:8010 — garaj koordinatalari, ixtiyoriy raqam, davr va chegaralar
uchun bitta forma. Natijada holatlar, ogohlantirishlar, davrlar, transport
tafsilotlari, AI va xom JSON ko'rsatiladi. Credentiallar faqat sahifa xotirasida.
Saqlangan hisobot yoki sun'iy GPS jonli ma'lumot sifatida berilmaydi.

Bu serverda startup worker, migratsiya yoki agent yo'q. ATIL so'rovlari
`READ ONLY`; bazaga yozilmaydi. GPS barcha manbalardan vaqtli bog'lanishlar
tekshirilgan holda paketlab olinadi. Monitoringda eski 200000 umumiy va
50000 transport/manba chegaralari qo'llanmaydi. Tanlangan davrdagi barcha
mos GPS qatorlari server kursori orqali o'qiladi. `FY_MONITOR_PACKET_POINTS`
(sukut 4000) faqat uzatish paketi hajmi; tarixni kesmaydi. Xotirada bir
transportning tarixi saqlanadi. O'qish uzilsa qisman hisob muvaffaqiyatli
hisobot sifatida qaytarilmaydi. `gps_read_complete` va `gps_rows_read`
o'qish yakunini ko'rsatadi, uzluksiz signal mavjudligini isbotlamaydi.
Tafsilotlar va ogohlantirishlar ro'yxati limiti alohida belgilanadi;
umumiy sonlar barcha o'qilgan nuqtalardan hisoblanadi.

GPS arxividan to'liq provider JSON o'rniga hisoblashga kerakli maydonlar
olinadi. Matnli JSONni xavfsiz tekshirish uchun PostgreSQL 16+ dagi
`pg_input_is_valid` ishlatiladi (joriy baza: PostgreSQL 17). Buzilgan JSON
yaroqli GPS nuqtasi sifatida olinmaydi. Aynan bir xil kuzatuvlar og'irligi
saqlanib birlashtiriladi. Bir vaqtdagi ziddiyatlar rad etiladi, ular orasida
kirish-chiqish yoki uzluksiz turish taxmin qilinmaydi.
Frontend shu bitta endpointga `Accept: text/event-stream` yuboradi.
Server hisoblash va AI bosqichlarini har 10 soniyada yangilaydi va oxirida
to'liq hisobotni beradi. Bir daqiqa yangilanish kelmasa ulanish xatosi
ko'rsatiladi; katta tarix uchun umumiy 6 daqiqalik bekor qilish yo'q.
Swagger va oddiy JSON mijozlar avvalgidek bitta JSON javob oladi.
Streamdagi xato `error` hodisasida haqiqiy status bilan beriladi;
to'liq o'qilmagan natija `report` hodisasi sifatida chiqmaydi.
Tarmoq, HTTP, JSON va ekranga chiqarish xatolari alohida ko'rsatiladi.

## GPS tezligi birligi

2026-10-31 kuni bazadagi `BEPULGPS` bog'lanishi uchun sozlangan server
`api.bepulgps.uz/api/server` orqali Traccar 6.7.1 formatini qaytardi.
[BEPULGPS ochiq frontendida](https://app.bepulgps.uz/) km/soatga o'tish
koeffitsienti 1.852 ekanligi tekshirildi. Bu
[Traccar Position API kontraktiga](https://github.com/traccar/traccar/blob/master/openapi.yaml)
mos: `speed` uzelda (knots). `BEPULGPS` uchun `speed * 1.852` ishlatiladi;
aniq `speed_kph` mavjud bo'lsa u ustun va qayta aylantirilmaydi.
`current.speed_basis` konversiya manbasini ko'rsatadi.

Noma'lum provayder tezligi birlik taxmini bilan hisobga olinmaydi.
Qo'shimcha tasdiqlangan integratsiyalar uchun `FY_ARCHIVE_SPEED_UNITS`
JSON xaritasi (`{"PROVIDER":"knots"}`) berilishi mumkin; ruxsat etilgan
birliklar: `knots`, `kph`, `mph`, `mps`. Yo'q tezlik nolga, yo'q motor
holati o'chirilgan holatga aylantirilmaydi. Garage koordinatalari namuna
bo'lsa natija ham shu namuna hududiga nisbatan hisoblanadi.

```powershell
.\venv\Scripts\python.exe -m pytest tests/test_fleet_monitor.py tests/test_fleet_monitor_streaming.py tests/test_fleet_yard.py tests/test_fleet_yard_ai.py tests/test_fleet_yard_web.py -q -p no:cacheprovider
```

`sample_points.json` eski geofence dvigatelining ichki test namunasi;
alohida public endpoint orqali xizmat qilmaydi.
