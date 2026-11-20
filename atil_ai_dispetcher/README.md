# ATIL AI Dispetcher — bitta «AI tahlili» oynasi

Loyiha mavjud baza ma’lumotlarini bitta dispetcher ish joyiga yig‘adi.
Eski AI Agent va Dispatcher Assistant alohida ishlamaydi: bitta worker ma’lumotni
yangilaydi, tekshiruvlarni bajaradi va kunlik AI xulosasini saqlaydi.

## Foydalanuvchi jarayoni

1. Kirganda **AI tahlili** ochiladi. Arizalar, transport, haydovchilar, reyslar,
   hujjatlar, GPS va garaj holati sodda o‘zbekcha matn bilan tushuntiriladi.
2. Tahlil boshida **Avval nima qilish kerak?** tavsiyalari chiqadi. Dalillar,
   ularning ma’nosi, ma’lumot yetishmasligi va hisob chegaralari matnda beriladi.
3. **Barcha arizalarga transport tanlash** navbatni birgalikda tekshiradi.
   Mos transportlar takrorlanmasdan tavsiya qilinadi, tanlanmagan har bir arizaning
   sababi chiqadi. GPS tarixi alohida transport uchun shu oynada tekshiriladi.
4. Oldingi tahlillar, avtomatik jadval va garaj sozlamalari shu sahifada ochiladi.
   Koordinata, radius va namuna belgisi saqlanadi; yangi hisob navbatga qo‘shiladi.

Frontendda baza jadvallari, xom JSON va bo‘limlar menyusi yo‘q.
Hisob vaqti ko‘rinadi; eski tahlil joriy holat deb taqdim etilmaydi.
Bir arizada miqdor yoki transport sig‘imi yetishmasa, mos deb tasdiqlanmaydi.
Haydovchi toifasi va barcha reys talablari dispetcher tekshiruviga qoladi.
Transport/haydovchi ATILda avtomatik biriktirilmaydi.

## Navbatdagi arizalarga transport tanlash — 2026-11-04

Har bir avtomatik yoki qo‘lda boshlangan `snapshot` / `briefing` hisobida
`sections.allocation` yaratiladi. Frontdagi bitta ariza tanlash formasi o‘rniga
umumiy tanlov tugmasi qo‘yildi. Eski `selection` API moslik uchun saqlandi.

- Arizalar ustuvorlik, reja vaqti, yaratilish vaqti va ID bo‘yicha ko‘riladi.
- Faqat faol, bandligi yo‘q, cheklovchi ta’miri/zid yozuvi yo‘q va bugungi
  texnik ko‘rigi tasdiqlangan transportlar nomzod bo‘ladi. Avvaldan navbatdagi
  arizaga biriktirilgan transport ham boshqa arizaga tavsiya qilinmaydi.
- Transport turi hamda arizadagi barcha musbat og‘irlik, hajm va yo‘lovchi
  talablariga moslik tekshiriladi. Miqdor yoki kerakli sig‘im noma’lum bo‘lsa
  mos deb olinmaydi. Manfiy va yaroqsiz miqdorlar aniqlashtirishga yuboriladi.
- Mos nomzodlar yuk olish nuqtasigacha yaqinligi bo‘yicha tartiblanadi:
  arizaning bevosita koordinatasi yoki yagona yaroqli `LOCATIONS` katalog
  koordinatasi hamda ko‘pi bilan 5 daqiqalik GPS nuqtasi kerak. Masofa to‘g‘ri
  chiziq bo‘yicha; yo‘l masofasi va yetib kelish vaqti emas. Nuqta yetishmasa
  nomzod chiqarib tashlanmaydi, yaqinlik noma’lum deb ko‘rsatiladi. Ko‘proq
  arizani qamrash uchun moslash qayta taqsimlanishi mumkin; har tanlov eng
  yaqin transport ekanligi yoki umumiy masofa minimumi kafolatlanmaydi.
- Har transport bir hisobda faqat bir arizaga tanlanadi. Moslashni qayta
  taqsimlash orqali qo‘shimcha arizani bajarish imkoni qidiriladi; yuqori
  ustuvorlikda moslangan ariza transportsiz qoldirilmaydi. Yuklar birlashtirilmaydi.
- Arizalar va transportlar har biri ko‘pi bilan 2000 yozuv. Kesilsa qamrov
  ochiq ko‘rsatiladi. Har arizaning tavsiyasi yoki sababi matnda mavjud;
  uzun ro‘yxatning dastlabki beshtasi ko‘rinadi, qolganlari shu kartochkada ochiladi.
- Tanlov joriy yozuvlar bo‘yicha tavsiya. Smena, kelajak bandligi, marshrut
  va yetib borish vaqti optimallashtirilmaydi. Haydovchilar bu hisobda
  taqsimlanmaydi; ularning tekshiruv natijasi va keyingi tekshiruvlar alohida aytiladi.
- `REVIEW_ONLY`: ATIL bazasiga yozish, transportni band qilish va tasdiqlash
  endpointi qo‘shilmadi. Biriktirish mavjud ATIL jarayonida amalga oshiriladi.

## Mavjud ma’lumotga tayangan beshta qo‘shimcha

Har davriy va qo‘lda boshlangan umumiy tahlilga quyidagi kartochkalar qo‘shiladi:

1. **Transportlar holati.** Har transport bir marta sanaladi: ishda deb qayd
   etilgan, rejalashtirilgan reys/ochiq yo‘l varaqasi bilan band, ta’mir sabab
   cheklangan, bloklangan/chiqarilgan, topshiriqsiz va asosiy tekshiruvlardan
   o‘tgan, tayyorligi tasdiqlanmagan yoki yozuvlari zid. Zid bandlik/ta’mir yoki
   faol reysdagi yakun belgisi alohida guruhga tushadi. Bu GPS harakati yoki
   avtomatik ishga chiqarish ruxsati emas. Bloklovchi ochiq ta’mir endi bitta
   ariza tekshiruvida ham hisobga olinadi; haydovchining availability cheklovi ham tekshiriladi.
2. **Oldingi hisobdan beri o‘zgarishlar.** Oldingi muvaffaqiyatli snapshot/kunlik
   hisob bilan taqqoslanadi. Ariza/reyslar barcha statuslar bilan, har manbadan
   ko‘pi bilan 20 000 ID olinadi. Yangi ariza yaratilish vaqti bilan tekshiriladi;
   eski sana bilan birinchi ko‘ringan yozuv alohida. Reys faqat avvalgi statusdan
   `COMPLETED`ga o‘tgani kuzatilsa yakunlangan deb sanaladi. Ro‘yxatdan yo‘qolish
   yakunlanish emas. Kesilgan yoki yetishmagan manbalar uchun farq noma’lum.
   Birinchi hisob boshlang‘ich holatni saqlaydi; keyingisida taqqoslash chiqadi.
3. **Ta’mir nazorati.** Ochiq naryadlar, transportlar, chiqishni cheklovchi belgi,
   ochilganidan beri o‘tgan vaqt, bosqich, qayd etilgan ishlar va bajarilgan bandlar.
   Faqat `estimated_completion_time` bor va vaqtlar mos bo‘lsa reja kechikishi
   hisoblanadi. Rejasiz ta’mirga tugash prognozi yoki o‘ylab topilgan me’yor yo‘q.
   Ta’mir jadvali bo‘sh bo‘lsa bu kartochka chiqarilmaydi.
4. **Arizalar kutishi va to‘siqlar.** Navbatdan olingan 2000 tagacha ariza uchun
   tasdiqlangan/yuborilgan/yaratilgan vaqtning qaysi biri ishlatilgani yoziladi.
   Transport turi, sig‘im va miqdor, bandlik, ko‘rik hamda haydovchi asosiy
   tekshiruvlari bitta ariza tekshiruvi bilan bir xil qoidalarga tayanadi.
   Bular hozirgi to‘siqlar; tarixiy kutishning aniq sababini isbotlamaydi.
   Smena, kelajak bandligi va haydovchi toifasi alohida tekshiriladi.
5. **Hujjatlarning biriktirilishi.** Guvohnoma/tibbiy ma’lumotnoma fayli qaydi
   bor va yo‘q haydovchilar, transport hujjatlari, fayl bog‘lanishi va muddatlari.
   Takror yuklangan fayllar haydovchi sonini ko‘paytirmaydi. Haydovchi fayli
   uchun bo‘sh bo‘lmagan manzil va musbat hajm tekshiriladi; fayl yuklab olinmaydi.
   Majburiy hujjatlar siyosati berilmagan: yo‘q fayl qonunbuzarlik yoki hujjatning
   o‘zi yo‘q degan xulosa emas. Shuning uchun bu funksiya to‘liq muvofiqlik
   nazorati emas, mavjud ma’lumot bo‘yicha biriktirish va muddat tekshiruvidir.

Hisoblar va manba sanalari mahalliy tarixda saqlanadi. ATILga yozilmaydi.
Ma’lumot olinmasa kartochka yoki qamrov izohida noma’lum deb ko‘rsatiladi.

## Ishga tushirish va avtomatika

```powershell
.\venv\Scripts\python.exe -m atil_ai_dispetcher --port 8020
```

UI: http://127.0.0.1:8020/ai-dispatcher/

V2 birinchi ishga tushganda eski sozlamalar bir marta migratsiya qilinadi:
avtomatik ishlash yoqiladi, oldingi rejalashtirish/risk/ETA kalitlari olib tashlanadi.
Har 15 daqiqada holat, GPS va matnli AI tahlili yangilanadi; kunlik AI xulosa 07:30 Toshkent vaqtida
(yoki oldin saqlangan vaqt/oraliqda) olinadi. Server keyinroq yoqilsa, kunlik xulosa bir marta tayyorlanadi.
Keyinchalik foydalanuvchi jadvalni o‘chirsa, qayta ishga tushish uni qayta yoqmaydi.
Kunlik hisob ulanish xatosi bilan tugasa, bir yangilash oralig‘idan keyin qayta
urinadi. Oldingi xato urinishlar tarixda qoladi; muvaffaqiyatli kunlik hisob takrorlanmaydi.
Brauzer 5 soniyada saqlangan natija va vazifa holatini tekshiradi.
Kompyuter o‘chiq bo‘lsa ishlamaydi; Windows kirishida avtomatik server ishga tushirish bu o‘zgarishga kirmaydi.

Hisoblangan faktlar matni LLM tomonidan o‘zgartirilmaydi. AI ularga qisqa izoh
qo‘shadi va mavjud tavsiyalardan ustuvorlarini tanlaydi. Javob sxemasi, fakt
qamrovi, yangi raqamlar, namuna va GPS cheklovlari tekshiriladi. Bu avtomatik
tekshiruv barcha semantik xatolarni istisno qilmaydi; qaror dispetcherda qoladi.
AI ishlamasa yoki javobi tekshiruvdan o‘tmasa, foydali hisoblangan tushuntirish
qoladi va **AI izohi olinmadi** deb ochiq yoziladi. AI o‘chirilganda ham matn bor.
Haydovchi ismlari, transport raqamlari, manzillar va GPS koordinatalari izoh
modeliga yuborilmaydi; qisqa dalil misollari ilovaning o‘zida shakllanadi.

Autentifikatsiyalangan `GET /ai-dispatcher/api/health` baza ulanishi va worker
holatini tekshiradi. Xatoda 503 va maxfiy ma’lumotsiz sabab kodi qaytadi.
`DATABASE_NETWORK_BLOCKED` tarmoq ruxsati cheklanganini bildiradi. Serverni bazaga
ulanish ruxsati bo‘lgan terminal/muhitda ishga tushiring; HTML ochilishi baza ishlayotganini anglatmaydi.

## Faol imkoniyatlardan chiqarildi

- Ko‘p arizani/yukni bitta mashinaga yig‘ish va marshrut optimizatori.
- Alohida AI Agent API, uning ikkinchi scheduler’i va tashqi xabar kanallari.
- Risk score, keskin harakatlar, tezlik buzilishi va ETA prognozi sahifalari/joblari.
- Bo‘sh telematika jadvaliga bog‘langan og‘ish/dvigatel bekor turishi nazorati.
- Bo‘sh sug‘urta/hodisa/jarima/sensor manbalariga tayanuvchi mezonlar.
- Eski reja tasdiqlash endpointi endi 410 qaytaradi.

Bu ishlar yangi vazifa API’sida qabul qilinmaydi, menyuga chiqarilmaydi va scheduler’da bajarilmaydi.
Oldingi natijalar tarixda faqat o‘qish uchun saqlanadi. Eski algoritm papkalari regressiya
va tarixiy kod uchun qolgan ichki kutubxonalar; faol `app.py`, `service.py`, `worker.py`
ularning eski router/joblarini ishga tushirmaydi. `fleet_yard_llm`dan provayder tezlik
birliklari va sinalgan sof geozona algoritmi qayta ishlatiladi.

## GPS API

[API qo‘llash va tekshirish](GPS_API_INTEGRATION.md). Joriy nuqta va alohida tarix
uchun API mavjud bo‘lmasa `gps_archive_point` zaxirasi bor. Har transport/natijada manba
ochiq ko‘rsatiladi. API maxfiy ma’lumoti frontendga chiqmaydi.

2026-11-04 da Bearer token bilan joriy joylashuv va tarix jonli tekshirildi.
`current-batch` javobidagi `entries[].position` qo‘llanadi; aniq bekor qilingan
GPS ruxsatida nuqta ko‘rsatilmaydi. Garaj va kunlik kuzatuv uchun API tarixi
bir marta olinib, ikki hisobda ishlatiladi. API sozlanganida ommaviy garaj
hisobi arxiv so‘roviga qaytmaydi; olinmagan tarix noma’lum deb ko‘rsatiladi.

`sections.gps_daily` bugun Toshkent yarim tunidan hisob vaqtigacha har bir
transportning masofasi, kuzatilgan harakat/to‘xtash va signal uzilishlarini
beradi. `daily-summaries`dagi `observedDistanceKm` to‘liq masofaga tenglashtirilmaydi;
kunlik API javobi mos kelmasa faqat uzilmagan GPS bo‘laklari masofasi taxminan
hisoblanadi. Noma’lum natija nol emas. Dvigatel ishlashi yoki sababsiz bekor
turish xulosasi chiqarilmaydi. Barcha transport javoblari bitta kartada,
dastlabki beshtadan keyingi javoblar shu joyda ochiladi.

## Faol kod

| Fayl | Vazifa |
|---|---|
| `app.py`, `router.py`, `models.py` | Yagona server va API kontrakti |
| `worker.py`, `store.py` | Avtomatik jadval, navbat, migratsiya va tarix |
| `service.py` | Manbalarni yig‘ish, hisoblangan tavsiyalar va AI izohi |
| `narrative.py`, `reading.py` | O‘zbekcha faktlar, tekshirilgan AI izohi va ixcham o‘qish API’si |
| `insights.py`, `insight_text.py` | Transport guruhlari, o‘zgarishlar, ta’mir, kutish va hujjat fayllari |
| `operations.py` | Haydovchi, transport, reys va bitta ariza tekshiruvi |
| `repository.py` | Read-only baza o‘qish yordamchisi va arizalar |
| `gps.py`, `gps_api.py` | GPS API, arxiv zaxirasi va bir xil natija shakli |
| `gps_activity.py` | Umumiy API tarixini yig‘ish va kunlik kuzatuv hisobi |
| `garage.py` | API/arxiv tarixidan kirish-chiqish va kuzatilgan to‘xtashlar |
| `frontend/` | Bitta AI tahlili oynasi, shu oynadagi javoblar va sozlamalar |

ATIL bazasida jadvallar o‘chirilmaydi yoki ma’lumot o‘zgartirilmaydi.
Mahalliy SQLite’da jadval sozlamalari va hisobotlar saqlanadi.

## Chegaralar

Arizalar: 2 000, reyslar: 500; jami son va ko‘rsatilgan son alohida.
Transport/haydovchi: 2 000; GPS joriy holat: 200. GPS arxiv tarixi: 5 000 nuqta;
API tarixi: 20 sahifa / 10 000 nuqta / taxminan 45 s va oxirgi so‘rov timeouti.
Ommaviy tarix: ko‘pi bilan 6 parallel mijoz, 90 s umumiy yig‘ish budjeti;
navbatdagi vazifa budjet tugasa tarmoqqa chiqmaydi. Kechikkan javoblar qisman hisob.
Kesilgan natija to‘liq deb ko‘rsatilmaydi. Eski GPS signali “hozir shu yerda” deyilmaydi.
Zonasiz eski reys vaqtlari kechikish uchun taxminan o‘girilmaydi.

## Garaj nazorati

UI: `/ai-dispatcher/` → **Avtomatik tahlil va garaj sozlamalari**.
Nom, kenglik, uzunlik va radius shu oynada saqlanadi.
`Namuna koordinatalarini qo‘yish` tugmasi 41.3, 69.24 va 200 m radiusni formaga kiritadi;
namuna tasdiqlangan haqiqiy garaj degani emas. Saqlangach darhol snapshot navbatga qo‘shiladi.
Jadvalni saqlash garaj sozlamalarini yo‘qotmaydi. Garaj ham har davriy snapshotda yangilanadi.

Standart davr 24 soat (1–168), uzoq to‘xtash chegarasi 15 daqiqa (5–1440).
Kirish/chiqish kamida 2 nuqta, 30 soniya va 30 m chegara zaxirasi bilan tasdiqlanadi.
To‘xtashda tezlik ko‘pi bilan 1 km/soat, kuzatilgan joy 50 m doirada bo‘lishi kerak.
300 soniyadan katta signal bo‘shlig‘i bekor turish vaqtiga qo‘shilmaydi; oxirgi
signaldan hozirgacha bo‘lgan vaqt ham hisobga qo‘shilmaydi. Sababsiz ishlamaslik yoki
dvigatel ishlayotgan holda turish GPSdan tasdiqlanmaydi.

Token sozlanganida manba — ATIL GPS API tarixi. Token sozlanmagan eski rejimda
`gps_archive_point` + tasdiqlangan vaqtli `vehicle_gps` bog‘lanishi saqlangan.
API oqimida faqat GPS kuzatuvi tanlangan transportlar qamraladi, butun park emas.
Har hisobda ko‘pi bilan 200 transport,
har transportdan dastlabki 2 000 nuqta olinadi; limit ko‘rsatiladi va kesilgan transportning
joriy holati tasdiqlanmaydi. Kirish/chiqish sonlari faqat kuzatilgan hodisalardir.
Namuna geozonadagi uzoq to‘xtashlar amaliy ogohlantirishlar ro‘yxatiga qo‘shilmaydi.
Eski arxiv rejimi timeouti 60 s; boshqa baza o‘qishlarda 10 s saqlangan.

## Tekshirish

```powershell
.\venv\Scripts\python.exe -m pytest tests/test_ai_dispetcher.py tests/test_dispatch_insights.py tests/test_dispatch_narrative.py tests/test_dispatch_gps_api.py tests/test_dispatch_garage.py tests/test_dispatch_health.py -q
node tests/test_ai_dispetcher_frontend.cjs
```
