# ATIL GPS API ulanishi

Kontrakt manbasi: [docs/atil-gps-history-api.md](../docs/atil-gps-history-api.md).
Hujjatning o‘zida haqiqiy javoblar sinovdan o‘tmagani qayd etilgan.

Umumiy adapter `gps_api.py`da, dispetcher oqimi `gps.py` va `gps_activity.py`da,
yoqilg‘i oqimi `oil_detection/gps_analysis.py` va `oil_detection/gps_daily.py`da.
GPS API faqat serverdan chaqiriladi.
2026-11-04 da Bearer token bilan jonli ulanish tekshirildi. Joriy joylashuv
HTTP 200 qaytardi, tarix so‘rovida nuqtalar olindi. Token faqat serverdagi `.env`da.
Loyiha frontining login/paroli GPS hisobiga almashtirib ishlatilmaydi.

## `.env` sozlamalari

```dotenv
ATIL_GPS_BASE_URL=https://api-atil.tenzorsoft.uz
# Bir usulni tanlang: tayyor token yoki alohida xizmat foydalanuvchisi.
ATIL_GPS_TOKEN=
ATIL_GPS_USERNAME=
ATIL_GPS_PASSWORD=
# Login javobining haqiqiy maydoniga moslang; nuqtali yo‘l qo‘llanadi.
ATIL_GPS_TOKEN_FIELD=accessToken
# Faqat akkaunt talab qilsa; bir martalik MFA avtomatik xizmat uchun barqaror emas.
ATIL_GPS_VERIFICATION_CODE=
```

Maxfiy qiymatlarni chatga yoki gitga yozmang. Sozlangach serverni qayta ishga tushiring.
Token tugasa `ACCESS_DENIED` qaytadi; yangi token qo‘yilishi kerak. Kunlik/garaj
kuzatuvi va yangi yoqilg‘i hisobi bu xatoni arxiv koordinatalari bilan yashirmaydi.
Login rejimida har yangi yig‘ish klienti login qiladi; takroriy login bo‘roni uchun avtomatik retry yo‘q.

## Tarix oqimi

1. `POST /api/v1/gps/history-selections`: UUID, UTC `fromInstant` va `toExclusive`.
2. `GET /api/v1/gps/history-selections/{id}`: `202` bo‘lsa 1 s kutish, umumiy budjet bilan.
3. `nextCursor` bo‘yicha davom etish; `pointOffset`, segment indekslari, tartib va selection ID tekshiriladi.
4. `410` bo‘lsa tanlov bir marta qayta yaratiladi; `401/403`, `502`, noto‘g‘ri shakl yoki vaqt tugashi tegishli oqimga xato sifatida qaytariladi.
5. `complete=false` / `limitExceeded=true` to‘liq tarix deb ko‘rsatilmaydi.

`segmentStarts` hozir sahifa ichidagi indekslar sifatida talqin qilinadi; backend bilan tasdiqlash kerak.
Sifat statistikasi sahifalar bo‘yicha saqlanadi: kumulyativ va sahifalik sonlar aralashtirib qo‘shilmaydi.
API tezligi `speedKmh` — qayta ×1.852 qilinmaydi. Xom BEPULGPS arxiv tezligi knotsdan o‘giriladi.
API `valid` bermasa sifat `API_VALIDITY_NOT_EXPOSED` deb belgilanadi; risk/keskin harakat hisobi bajarilmaydi.

## Joriy joylashuv

`GET /api/v1/gps/current-batch?vehicleIds=<vergul bilan UUIDlar>`; ko‘pi bilan 100 ID/so‘rov.
Jonli javob shakli: `{updatedAt, wireVersion, staleThresholdSeconds,
entries:[{vehicleId, position:{fixTime, latitude, longitude, speedKmh, ...}, ...}],
accessRevokedVehicleIds:[...]}`. Adapter `entries[].position` ni vehicleId bilan
bog‘laydi; `position=null` yaroqli nuqta emas. Eski ro‘yxat yoki `{items:[...]}`
shakli ham saqlangan. Aniq bekor qilingan IDlar uchun arxiv nuqtasi ko‘rsatilmaydi.
Tartib orqali mashina bilan nuqta bog‘lanmaydi. Boshqa DTO bo‘lsa xato yashirilmaydi:
`CURRENT_CONTRACT_UNCONFIRMED` va arxivga o‘tish natijada ko‘rsatiladi.

## Kunlik xulosa va garaj — 2026-11-04

`GET /api/v1/gps/daily-summaries?vehicleIds=...` ulandi. Jonli DTO:
`{items:[{vehicleId,date,timeZone,asOf,distanceKm,observedDistanceKm,gpsState,...}]}`.
Har ID, vaqt zonasi va sonlar tekshiriladi. `distanceKm=null` nol emas;
`observedDistanceKm` faqat GPS kuzatgan masofa sifatida ko‘rsatiladi. Hisob
Toshkent kuniga tegishli bo‘lishi, `asOf` yangi bo‘lishi kerak. Mazkur
endpointdagi yoqilg‘i maydonlari bu GPS tahlilida ishlatilmaydi.

`gps_activity.collect` har avtomatik/qo‘lda hisobda bitta chegaralangan tarix
to‘plamini yig‘adi: bugungi kun va garaj davridan ertaroq boshlanishdan hozirgacha.
6 parallel mijoz, 200 transport, umumiy 90 s budjet. API tarixining sahifa,
nuqta va so‘rov limitlari saqlangan. `garage.report(..., observations=batch)`
DB arxivini qayta o‘qimaydi. Xato va ruxsat bekor bo‘lishi arxiv koordinatasi
bilan yashirilmaydi. Signal uzilishlari kirish-chiqish yoki to‘xtashga ulanmaydi.
Oxirgi yaroqsiz nuqta joriy to‘xtash holatini tasdiqlashga yo‘l qo‘ymaydi.

`sections.gps_daily` har transportning manbasi, davri, masofa turi
(`TOTAL`, `OBSERVED`, `ESTIMATED`), kuzatilgan daqiqalar va ma’lumot cheklovini
saqlaydi. Kunlik API bo‘sh/xato/eski bo‘lsa segmentlar orasini ulamasdan
nuqtalardan taxminiy masofa hisoblanadi; bitta nuqta masofa hisoblash uchun yetmaydi.
Garaj namuna 41.3, 69.24 / 200 m bo‘lib turadi; `is_example=true` saqlanadi.

Dispetcherning kunlik oqimi `daily-summaries` va tarix nuqtalaridan foydalanadi.
`/history-selections/{id}/distance` endi quyidagi yoqilg‘i oqimiga ulangan;
dispetcherning kunlik masofasi shu endpointga o‘tkazilmagan. WebSocket,
`?at=`, `/map`, oddiy `/history` va tashqi API yoqilg‘i endpointlari ish
oqimiga ulanmagan.

## Yoqilg‘i hisobi uchun reys masofasi

`oil_detection/gps_analysis.py` mavjud adapter bilan yo‘l varaqasining haqiqiy
chiqish–qaytish oralig‘i uchun tarix oladi, keyin:

```http
GET /api/v1/gps/history-selections/{id}/distance
```

Adapter selection ID, vaqt chegaralari, `complete`, `gapCount` va manfiy/
cheksiz bo‘lmagan masofalarni tekshiradi. To‘liq reys masofasi sifatida faqat
`source=GPS_TRACK`, `complete=true`, `gapCount=0`, davri aynan mos javob
qabul qilinadi. Tarix sahifalari ham to‘liq va toza bo‘lishi, aniqlangan signal
uzilishi bo‘lmasligi, kamida ikki nuqta hamda reys bosh-oxiriga 120 soniya
ichida nuqtalar bo‘lishi kerak.

Shundan keyin shu hujjatdagi sarf aynan shu GPS masofasiga bo‘linadi. Qisman
qamrovda kuzatilgan masofa yoki nuqtalardan taxminiy masofa ko‘rsatiladi,
100 km sarf va ortiqcha sarf chiqarilmaydi. `ODOMETER` yoki noma’lum manbadan
kelgan masofa GPS masofasi sifatida ishlatilmaydi. API ruxsati/xatosi, bo‘sh
tarix va nol masofa bir xil holat emas; yoqilg‘i oqimi arxivga qaytmaydi.

Masofa sarfi uchun `KM_ONLY` (shuningdek `KM`, `DISTANCE`) rejimi kerak.
`MOTOHOURS_ONLY`, `KM_AND_MOTOHOURS`, noma’lum rejim, bo‘sh yoqilg‘i turi yoki
gazning tasdiqlanmagan birligi bilan litr/100 km hisoblanmaydi. Norma haqiqiy
reysning butun davriga mos bazadagi `fuel_norm`dan olinadi. GPS bak sathini,
yoqilg‘i o‘g‘irlanishini yoki dvigatel ishlaganini o‘lchamaydi.

Quyish vaqtiga eng yaqin GPS nuqtasi 120 soniya ichida bo‘lsa kuzatilgan joy
ko‘rsatiladi. Faqat haqiqiy shoxobcha koordinatasi mavjud bo‘lganda unga
to‘g‘ri chiziqli masofa hisoblanadi; radius yoki «mos/mos emas» bahosi
o‘ylab topilmaydi. 2026-11-04 bazani o‘qib tekshirishda quyish yozuvlariga
bog‘langan yaroqli shoxobcha koordinatalari topilmadi. Bu joy masofasi uchun
ma’lumot bo‘shlig‘i; mavjud GPS nuqtasini ko‘rsatishga to‘sqinlik qilmaydi.

Foydalanuvchi yangi oqimni HTTP Basic bilan himoyalangan
`GET /oil-detection/gps-daily?day=YYYY-MM-DD` orqali yoki yoqilg‘i frontidagi
«Kunlik GPS va yoqilg‘i xulosasi» tugmasidan ishga tushiradi. Hisob faqat shu
Toshkent kuni ichida boshlangan va tugagan, vaqti/reys bog‘lanishi takrorlanmagan
hujjatlar uchun; butun kun masofasi boshqa davr sarfiga bo‘linmaydi.
Ko‘pi bilan 50 hujjat, to‘rtta parallel ishchi, 90 soniya GPS yig‘ish budjeti bor.
`POST /oil-detection/investigate` ham GPSni LLMdan oldin avtomatik tekshiradi.

Natijalar bitta ko‘k ish oynasida tushunarli kartochkalar bilan chiqadi.
Kunlik xulosaning qo‘shimcha LLM izohi olinmasa hisoblangan natija saqlanadi;
bu `/scan` yoki `/investigate` uchun LLM talabini o‘zgartirmaydi. Token,
login/parol va xom GPS payloadlari LLMga yuborilmaydi; agent dalilida aniq
koordinata va qurilma IDsi ham chiqarib tashlanadi.

Batafsil kontrakt: [Yoqilg‘i agenti va GPS hisobi](../oil_detection/INVESTIGATION.md).

## Tekshirilgan / tekshirilmagan

- Mock HTTP testlar: login maydoni, pagination, pending, timeout, expired, permission,
  takroriy cursor, limit, DTO identifikatsiyasi, tezlik birligi va arxivga qaytish.
- Jonli ATIL DB arxivi: tekshirildi, nuqtalar olindi.
- Jonli ATIL GPS API: 2026-11-04 da Bearer token qabul qilindi; joriy nuqta va
  bir soatlik tarix sinovdan o‘tdi. Dalil: `.codex_run/gps-token-live.json`.
  Nuqtalar manbasi API bo‘lsa ham ularning vaqti eskirgan bo‘lishi mumkin.
- `.env`dagi tokenning keyingi bo‘sh takroriy qatori oldingi qiymatni bosib
  qolishi mumkin; jonli ulashda shunday bo‘sh qator olib tashlandi.
