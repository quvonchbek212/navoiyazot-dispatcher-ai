# Tekshiruv qaydlari

## GPS asosida uchta qo‘shimcha — 2026-11-04

- To‘liq regressiya **1232 passed, 36.28 s**. Dastlab sandbox tarmog‘i sabab
  19 ta mavjud DB integratsiya testi bajarilmagan; o‘qish ruxsati bilan to‘liq
  qayta bajarildi. Keyingi qo‘shimcha trailing-invalid regressiyasi bilan GPS,
  garaj va matn testlari **122 passed**. Frontend DOM sinovi o‘tdi.
- Yangi chekka holatlar: yaqin transport, eski/kelajak/yaroqsiz GPS, manzil
  yo‘qligi, ustuvorlik va bir martalik tanlov; kunlik null/haqiqiy nol,
  noto‘g‘ri ID/kun/vaqt zonasi, uzilishlar, chiqish limiti, bekor qilingan ruxsat;
  qisman va oxirgi yaroqsiz kuzatuvdan joriy to‘xtash xulosasini chiqarmaslik.
- Jonli qo‘lda snapshot **57 s**, AI `COMPLETE`, API garaj tarixi **70/70**
  transport uchun olindi, shu urinishda manba xatolari yo‘q.
  Dalil: `.codex_run/gps-features-live.json`.
- Keyingi avtomatik snapshot, **12:30 Toshkent**: kunlik **70** transportdan
  **60** tasida API kuzatgan masofa, **10** tasida masofa noma’lum; to‘liq kun
  deb ko‘rsatilmagan. Namuna garaj API asosida, **65** tarix olindi, **5**
  olinmadi, joriy holatlar tasdiqlanmagan deb ko‘rsatildi. Shu urinishda alohida
  `change_index` DB o‘qishi timeout bo‘ldi va qamrov matnida yashirilmadi.
  Dalil: `.codex_run/gps-features-latest.json`.
- 452 arizada yuk olish koordinatasi yo‘q, to‘liq tayyor nomzod 0; masofa
  yoki tavsiya o‘ylab topilmadi. 385 ma’lumot yetishmagan, 61 avvaldan
  biriktirilgan, 6 mos nomzodsiz ariza ochiq ko‘rsatiladi.
- Haqiqiy brauzer: login, kunlik 70 javob, «qolgan 65» ochilishi, namuna
  garaj belgisi, bitta oynada jadvalsiz matn; 390 px ekranda gorizontal chiqish
  yo‘q, JS xatolari yo‘q. Dalil `.codex_run/gps-features-browser-check.json`,
  rasmlar `gps-features-daily-desktop.png`, `gps-features-daily-mobile.png`,
  `gps-features-garage-desktop.png` (barchasi `.codex_run/`da).
- Server: `http://127.0.0.1:8020/ai-dispatcher/`; log
  `.codex_run/dispatcher-gps-features-verified-server.log`. ATILga yozish yo‘q.

## Bearer token bilan jonli GPS — 2026-11-04

- `.env`dagi oldingi tokenni bosib qolgan keyingi bo‘sh `ATIL_GPS_TOKEN`
  qatori olib tashlandi. Maxfiy qiymat vosita natijalari, kod yoki logga chiqarilmadi.
- Haqiqiy `current-batch` HTTP 200 javob berdi. DTO `entries[].position`
  ekanligi tasdiqlandi; `vehicleId` bo‘yicha bog‘lash, null nuqta, takror/noto‘g‘ri
  identifikator va aniq bekor qilingan ruxsatlar uchun tekshiruvlar qo‘shildi.
- To‘liq regressiya: **1114 passed, 20.62 s**. GPS/narrative/garaj bo‘yicha
  alohida **46 passed**. Ruxsati bekor qilingan transportga arxiv nuqtasi qaytarilmaydi.
- Jonli bevosita sinov: joriy API nuqtasi yaroqli, bir soatlik tarix to‘liq.
  Qayta ishga tushirilgan serverda GPS vazifasi **22 s**, **36 ta nuqta**,
  `source=ATIL_API`, AI `COMPLETE` bilan tugadi.
- Dalillar: `.codex_run/gps-token-live.json`, `.codex_run/gps-front-live.json`.
  Server logi: `.codex_run/dispatcher-gps-live-server.log`.
- Umumiy front hisobi **83 s** da tayyorlandi: **70/70 nuqta `ATIL_API`**,
  1 tasi 5 daqiqa ichidagi yangi signal, 69 tasi eskirgan. API fallback yo‘q,
  `api_configured=true`, AI `COMPLETE`, health `ready`. Front manba matni
  API orqali olinganini ko‘rsatishi tekshirildi. Shu urinishda alohida garaj
  arxivini o‘qish xatosi yashirilmagan; GPS API manbasi muvaffaqiyatli.
- Garaj DB arxivini ishlatadi; WebSocket, masofa, xarita va kunlik GPS API
  endpointlari bu o‘zgarishga kiritilmadi. API nuqtasining eskirishi alohida hisoblanadi.

## Arizalarga takrorlanmaydigan transport tanlovi — 2026-11-04

- Umumiy regressiya: **1106 passed, 21.94 s**. Keyingi ikki chekka holat
  (faqat haydovchi biriktirilgan ariza va nol tavsiyada matn) qo‘shilgach,
  taqsimlash + narrative bo‘yicha **45 passed**; frontend DOM regressiyasi ham o‘tdi.
- 30 ariza / 18 transport sinovi: 18 alohida tavsiya, 12 transport yetishmasligi.
  Katta transportni kichikroq mos transportga almashtirib qo‘shimcha arizani
  qamrash, ustuvorlik, ko‘rik/bandlik/ta’mir, sig‘im, noma’lum miqdor, mavjud
  biriktirish, bir transportni qayta ishlatmaslik va qisman manbalar tekshirildi.
  Moslash hajmi 40 kichik tasodifiy grafikda to‘liq variantlar hisobiga teng.
- Jonli hisob, 10:59 Toshkent: **452/452 ariza** ko‘rildi. 385 `NEEDS_DATA`,
  61 `ALREADY_BOUND`, 6 `NO_MATCH`, 0 `RECOMMENDED`, 0 `SHORTAGE`.
  63 transportda bandlik/holat cheklovi qayd etilmagan, ammo barcha asosiy
  tekshiruvlardan o‘tgan transport 0. Tavsiyalar uydirilmadi.
- Jonli AI xulosasi `COMPLETE`; barcha 452 arizaning sababi matnli APIda bor.
  Alohida garaj manbasi bu urinishda o‘qilmadi va umumiy hisobotda ochiq aytildi;
  bu ariza/transport moslash manbalariga ta’sir qilmadi.
- Brauzer: eski ariza tanlagichi yo‘q, umumiy tanlov formasi bor, 447 ta
  qolgan ariza shu oynada ochiladi. 30/18 sun’iy misol faqat test brauzerida
  belgilangan holda ko‘rsatildi. 390 px ekranda gorizontal chiqish yo‘q,
  JS xatolari yo‘q. ATIL bazasiga hech qanday biriktirish yozilmadi.
- Dalillar: `.codex_run/allocation-live.json`, `.codex_run/allocation-browser-check.json`.
  Ishlayotgan front: `http://127.0.0.1:8020/ai-dispatcher/`.
- Yakuniy qayta hisob 11:10 Toshkentda boshlandi, 85 s da tugadi: tanlov
  `COMPLETE`, AI `COMPLETE`, yuqoridagi 452 ariza taqsimoti o‘zgarmadi.
  Nol tavsiyada avval ma’lumot/tayyorlikni aniqlashtirish aytiladi; texnik
  joylashuv UUIDsi manzil nomi o‘rnida ko‘rsatilmaydi. Server logi:
  `.codex_run/dispatcher-allocation-final-server.log`.

## Besh qo‘shimcha funksiya — 2026-11-03

- Jami **1068 test o‘tdi, 19.33 s**, skip/deselect yo‘q. Baza bilan bog‘liq testlar
  tarmoq ruxsati bilan bajarildi. Tegishli modullar alohida: **94 passed**.
- Yangi testlar: transport guruhlari takrorlanmasligi, bloklovchi ta’mir va
  haydovchi availability cheklovi, noto‘g‘ri/zonasiz vaqtlar, rejasiz ta’mirga
  kechikish bermaslik, bitta transportning ikki naryadini alohida hisoblash,
  yo‘qolgan reysni yakunlangan demaslik, kech qo‘shilgan eski ariza, kesilgan
  taqqoslash, noma’lum va nol farqi, takror hujjat fayllarini odam soniga qo‘shmaslik,
  qisman manba xatosi va avtomatik hisobda oldingi snapshot bilan solishtirish.
- Front JS syntax va mavjud DOM xulq testlari o‘tdi. Yangi beshta kartochka
  o‘sha matnli render orqali chiqadi; xom jadvallar yoki yangi modul sahifalari yo‘q.
- Jonli manba profilingi: `.codex_run/dispatch-extension-profile.json`.
  Yangi SQL va hisoblarning tekshiruvi: `.codex_run/extensions-live-check.json`.
- Majburiy hujjat siyosati berilmagan. Ishlaydigan qism — fayl qaydi, biriktirish
  va mavjud muddatlar tekshiruvi; qoidabuzarlik yoki to‘liq huquqiy muvofiqlik
  xulosasi berilmaydi. Ochiq ikki ta’mirda tugash rejasi yo‘q; bu kechikish emas.

Jonli serverning ketma-ket hisoblari dalili: `.codex_run/extensions-http-check.json`.

- Jonli HTTP tekshiruv, 18:37–18:40 Toshkent: ikkita umumiy hisob **41 s / 43 s**,
  ikkalasida AI `COMPLETE`, manba xatolari `{}`. Ikkinchi hisobda `COMPARED`,
  yangi ariza/yakunlangan reys/transport guruhi o‘zgarishlari nol; noma’lum manba yo‘q.
- Front uchun API beshta yangi kartochkani qaytardi; backenddagi xom manba
  indekslari matnli APIga chiqarilmadi. Ariza tekshiruvi `REVIEW_ONLY` bilan tugadi.
  Uning LLM javobi validatordan o‘tmadi (`ValueError`): `UNAVAILABLE` belgisi va
  bazadan hisoblangan matnli zaxira javob tekshirildi. Bu chaqiruvda LLM muvaffaqiyati
  da’vo qilinmaydi; umumiy ikki AI tahlili muvaffaqiyatli bajarildi.
- Server: `http://127.0.0.1:8020/ai-dispatcher/`. Log:
  `.codex_run/dispatcher-extensions-server.log`. Health `ready`, baza `read_only=on`,
  worker faol, avtomatik AI tahlili har 15 daqiqada yoqilgan.
- Brauzerda vizual tekshiruv bajarilmadi; JS syntax, DOM xulqi va jonli HTTP tekshirildi.

## Matnli AI tahlili — 2026-11-03

- UI qayta yozildi: bitta «AI tahlili» oynasi. Jadval, xom JSON, modul menyusi
  va modal javoblar olib tashlandi. Ariza/GPS natijalari shu oynada matn bo‘lib chiqadi.
- To‘liq regressiya: **1039 passed in 16.61s**, skip/deselect yo‘q. Baza bilan
  bog‘liq testlar uchun tarmoq ruxsati kerak bo‘ldi. Cheklangan muhitdagi oldingi
  urinishning ulanish xatolari kod nuqsoni emasligi ruxsatli yugurishda tekshirildi.
- Yakuniy umumlashtiruvchi matn tuzatishidan keyin tegishli **36 test o‘tdi**.
- Front DOM testi: bitta oyna, matn/AI javobini escape qilish, ustuvor tavsiyalar,
  eski hisob belgisi, davom etayotgan/xato vazifa, kiritilayotgan sozlamalarni
  saqlash, shu oynadagi tarix, namuna garaj va logout paytidagi kechikkan javoblar.
  `node tests/test_ai_dispetcher_frontend.cjs` va eski monitor regressiyasi o‘tdi.
- Haqiqiy model saqlangan dalillar asosida **COMPLETE** javob berdi: to‘qqizta
  hisoblangan matnning eng muhim uchtasiga AI izohi qo‘shildi. Dastlabki uzun
  javob timeoutga uchragani uchun model chiqishi qisqartirildi; fallback tekshirildi.
  Dalil: `.codex_run/prose-llm-check.json`.
- Taqdimot mazmuni yangilandi va offline `ATIL_AI_TAQDIMOT.html` qayta yig‘ildi.
- Yakuniy server `http://127.0.0.1:8020/ai-dispatcher/`da ishlayapti; loglar
  `.codex_run/dispatcher-prose-server.log`ga yoziladi. Himoyalangan health 200,
  baza `read_only=on`, worker faol; autentifikatsiyasiz yangi API 401 qaytardi.
- Yakuniy jonli HTTP sinovi, 17:12–17:13 Toshkent: umumiy tahlil **34 s**,
  ariza **16 s**, GPS tarixi **14 s**; uchalasida `source=llm`,
  `ai_status=COMPLETE`. Snapshot manba xatolari `{}`. Garaj mavjud, ammo namuna
  hudud va nuqta chegarasi sabab `PARTIAL`; bu to‘liq kuzatuv deb talqin qilinmaydi.
  Avtomatik yangilash 15 daqiqa, AI izohi yoqilgan. Yangi jadvalning AI parametrini
  unit test tekshiradi; HTTP dalilidagi eski avtomatik joblar yangi matn testiga qo‘shilmadi.
- Oldingi jonli urinishda garaj `QueryCanceled` bilan qisman qaytgan, AI xulosasi
  saqlangan. Server qayta ishga tushirilib, konsol chiqishi faylga yo‘naltirilgach
  yuqoridagi yakuniy sinov manba xatosisiz o‘tdi. Bu doimiy tarmoq/SQL tezligi kafolati emas.
- Brauzer runtime ro‘yxati bo‘sh qaytdi (`[]`); haqiqiy brauzerda vizual tekshiruv
  bajarilmadi. DOM va HTTP tekshiruvlari vizual screenshot tekshiruvi o‘rnida da’vo qilinmaydi.

Jonli HTTP dalili: `.codex_run/prose-http-check.json`. Oldingi tekshiruvlar quyida tarix sifatida saqlangan.

## To‘liq tekshiruv va ishga tushirish — 2026-11-03, 16:05 Toshkent

- Yakuniy yagona pytest yugurishi: **1026 passed in 17.89s**, skip yoki
  deselect yo‘q. Buyruq: `python -m pytest tests -q --tb=short -rs -p no:cacheprovider`.
  Tarmoq ruxsati bilan jonli SQL katalogi, davlat raqamlari va sxema mosligi ham tekshirildi.
- Ikkala JS DOM harness o‘tdi: `test_ai_dispetcher_frontend.cjs` va
  `test_monitor_frontend.cjs`. App, garaj va taqdimot JS syntax tekshiruvi o‘tdi.
- Server qayta ishga tushirildi: `http://127.0.0.1:8020/ai-dispatcher/`.
  Autentifikatsiyalangan health: HTTP 200, baza `ok`, `read_only=on`, worker ishlayapti.
  Autentifikatsiyasiz API HTTP 401; UI, CSS/JS va ikkala taqdimot manzili HTTP 200.
- Cheklangan muhitdan TCP va PostgreSQL ulanishi `permission_denied` qaytardi;
  tarmoq ruxsati bilan xuddi shu baza 0.12 s ichida o‘qildi. Server tarmoq
  ruxsati bor muhitda to‘g‘ridan-to‘g‘ri ishga tushirilgach yangi hisoblar muvaffaqiyatli bajarildi.
- Barcha faol job turlari haqiqiy HTTP orqali sinovdan o‘tdi:
  snapshot `COMPLETE`, bitta ariza tekshiruvi `REVIEW_ONLY`, GPS tarixi `complete`,
  shu kunning avtomatik AI hisoboti `COMPLETE` va AI izohi `COMPLETE`.
  Avtomatik snapshot ham alohida muvaffaqiyatli saqlandi.
- Tekshiruvdagi manbalar: 163 transport, 259 haydovchi, 452 kutayotgan ariza,
  326 faol reys, 70 GPS bog‘lanishi. Tanlangan ariza turida 49 transport ko‘rildi;
  asosiy talablardan o‘tgan transport/haydovchi 0 — avtomatik biriktirish bajarilmadi.
- GPS arxivi: bir soatlik birinchi namuna 0 nuqta; oxirgi signali mavjud boshqa
  transportning 24 soatlik tarixida **148 nuqta**, chiqarib tashlangan yoki kesilgan nuqta yo‘q.
  Eng yangi tekshirilgan signal 02:48:44 Toshkent; bu hisob vaqtida jonli signal emas.
- Garaj: namuna zona saqlandi; 163 transport, 44 tarixiy uzoq to‘xtash epizodi.
  Kirish/chiqish tasdiqlanmadi. Joriy holatlar noma’lum; ayrim tarixlar 2 000 nuqta
  chegarasida kesilganligi sabab garaj `PARTIAL`. Namuna haqiqiy garaj deb talqin qilinmaydi.
- GPS API credentiallari sozlanmagan (`NOT_CONFIGURED`): jonli GPS API tekshirilmagan;
  adapter kontrakt/xato/fallback testlari o‘tdi, amalda GPS arxivi ishlatildi.
- Tuzatishlar: maxfiy ma’lumotsiz health/sabab kodi, kunlik xato hisobni bitta
  intervaldan keyin qayta urinish, eski urinishlarni saqlash va takror ishni cheklash.
  Sxema tavsifi 794 o‘qiladigan jadval/view va 8 775 ustunga yangilandi;
  metadata so‘rovlari OID bo‘yicha cheklangan. CHECKsiz statuslar uchun kuzatilgan
  qiymatlar saqlandi, yangi status/tur tarjimalari va bo‘shliqli davlat raqami qidiruvi tuzatildi.
- Dalillar: `.codex_run/dispatch_database_check.json`,
  `.codex_run/dispatch_all_http_nov03.json`, `.codex_run/gps_history_24h_nov03.json`.
  Oldingi DDL nusxasi `.codex_run/ddl-before-nov03.sql`da. ATIL bazasiga yozuv kiritilmadi.
- Brauzer discovery ro‘yxati bo‘sh bo‘ldi. Haqiqiy brauzerda vizual/klik QA
  bajarilmadi; DOM va HTTP sinovlari vizual QA o‘rniga da’vo qilinmaydi.

## Garaj nazorati qayta qo‘shildi — 2026-11-02, 19:08 Toshkent

- Foydalanuvchi namuna so‘radi: 41.3, 69.24, radius 200 m,
  `is_example=true`. Bu haqiqiy korxona garaji deb tasdiqlanmagan.
- UI 11 sahifaga kengaydi: “Garaj nazorati” GPSdan keyin keladi. Koordinata,
  radius, davr va to‘xtash chegarasi saqlanadi. Saqlash darhol hisobni navbatga qo‘shadi.
- Jonli HTTP orqali saqlash va fon hisobini tekshirish o‘tdi: snapshot `COMPLETE`,
  manba xatolari yo‘q, garage.js HTTP 200, jadval yoqilgan / 15 daqiqa.
- Garaj arxiv hisobi: 162 transport; 60 tasida davrda yaroqli nuqta, jami 33 046 nuqta.
  166 uzoq to‘xtash epizodi ajratildi; namuna hududda kirish/chiqish tasdiqlanmadi.
  Barcha 162 transportning joriy holati noma’lum: eski signal, nuqta yetishmasligi
  yoki kesilgan tarix sababli. Bu 162 mashina bekor turgan degani emas.
- Ayrim transportlar uchun 2 000 nuqtalik chegara ishladi: garaj natijasi `PARTIAL`.
  Sonlar butun davrdagi barcha hodisalar deb ko‘rsatilmaydi. To‘g‘ridan-to‘g‘ri
  arxiv smoke 50.23 s; ommaviy garaj SQL uchun 60 s timeout belgilandi.
- Namuna geozona operatsion uzoq to‘xtash ogohlantirishi yaratmaydi. AIga yuborilgan
  agregatlarda ham namuna belgisi bor. ATILga yozuv yoki biriktirish bajarilmadi.
- Dalillar: `.codex_run/garage_v2_smoke.json`, `.codex_run/garage_v2_runtime.json`.
- Qoida testlari: dastlabki ichki nuqta kirish emas; signal bo‘shlig‘i,
  yaroqsiz nuqta, binding almashishi, ziddiyatli timestamp, imkonsiz sakrash,
  noma’lum tezlik va kesilgan tarix yolg‘on kirish/chiqish yoki bekor turish yaratmaydi.
- Backend va qayta ishlatilgan geozona regressiyasi: **95 passed**.
  Frontend DOM testi: 11 sahifa, namuna belgisi, eski zona natijasini yashirish,
  signal holati va HTML escaping o‘tdi. JS syntax tekshirildi.
  Brauzer sessiyasi mavjud emasligi sabab vizual QA bajarilmadi.

## Amaldagi v2 — 2026-11-02, 18:15 Toshkent

Quyidagi eski v1 qaydlari tarixiy. Faol imkoniyatlar va avtomatika uchun shu v2 bo‘limi hamda README asos bo‘ladi.

- Jonli bazada faqat o‘qish orqali tekshirildi: 162 transport, 257 haydovchi,
  452 kutayotgan ariza, 325 faol reys va 70 GPS bog‘lanishi. Sonlar tekshiruv vaqtiga tegishli.
- V2 snapshot barcha manbalarni xatosiz oldi (`COMPLETE`). Bitta ariza bo‘yicha
  tekshiruv bajarildi, talablarning barchasidan o‘tgan nomzod topilmadi;
  `REVIEW_ONLY` qaytdi. Bu avtomatik biriktirish muvaffaqiyati deb ko‘rsatilmaydi.
- Bir transportning bir soatlik GPS arxividan 2 nuqta olindi. API credential
  yo‘qligi `NOT_CONFIGURED` bilan ochiq qaytdi. Haqiqiy GPS API autentifikatsiyasi
  va server kontrakti hali tekshirilmagan; adapter mock HTTP testlaridan o‘tdi.
- Lokal server: HTTP 200, API versiyasi 2. Avtomatik jadval yoqilgan,
  interval 15 daqiqa, kunlik vaqt 07:30. Scheduler kunlik hisobotni saqladi,
  manba xatolari yo‘q, AI izohi `COMPLETE`. Server ishlashi jadval uchun zarur.
- Eski risk/ETA frontend asseti HTTP 404; yangi frontend HTTP 200.
  Eski beshta router faol ilovada ro‘yxatdan o‘tmaydi.
- V2 backend/GPS va saqlangan sof algoritm regressiyasi: **50 passed**.
  Keng regressiya yugurishi: **979 passed, 2 skipped, 19 deselected, 1 failed**.
  Yagona xato eski router faol bo‘lishini kutgan test edi; v2 kontraktiga
  moslashtirilib, tegishli testlar bilan qayta bajarildi: **32 passed**.
  Butun to‘plam qayta yugurilgani yoki bazaga bog‘liq 19 katalog testi
  ushbu yugurishda o‘tgani da’vo qilinmaydi.
- Frontend DOM testi o‘tdi: 10 sahifa tartibi, bitta ariza tekshiruvi,
  bo‘sh qiymatlar, HTML escaping, autentifikatsiya va hisobot holatlari.
  JS syntax tekshirildi. Brauzer sessiyasi mavjud bo‘lmagani uchun vizual QA bajarilmadi.
- Taqdimot v2 jarayoniga mos 6 slaydga yangilandi, mustaqil HTML qayta yig‘ildi.
- Dalillar: `.codex_run/dispatch_v2_smoke.json`,
  `.codex_run/dispatch_v2_running.json`. Migratsiyadan avval mahalliy hisobot
  bazasi `.codex_run/dispatch-before-v2.sqlite3`ga zaxiralandi.
- ATIL bazasi o‘zgartirilmadi; transport biriktirish yoki tashqi xabar yuborish bajarilmadi.

## Haydash xavfsizligi va ETA — 2026-11-02

- Yangi modul va dispetcher integratsiyasi: **47 passed** (`test_dispatch_intelligence.py`, `test_ai_dispetcher.py`).
- UI DOM tekshiruvi: **13 bo‘lim**, xavfsizlik/ETA natijalari, HTML escaping, noma’lum qiymatlar,
  navbat va autentifikatsiya holatlari o‘tdi. Yangi JS fayli syntax tekshiruvidan o‘tdi.
- Keng regressiya: sandboxda **976 passed, 2 skipped, 19 failed**; barcha 19 xato
  eski SQL katalog testlarining tarmoq chekloviga duch kelishidan edi.
  Shu 19 test ruxsat bilan alohida qayta bajarildi: **18 passed, 1 failed**.
  Qolgan xato — mavjud `atil_chatbot/ddl.sql` sxemasining jonli bazadan orqada qolishi.
  Bu ikki yugurishdan keyin bitta sxema mosligi tekshiruvi ochiq qolgan; butun to‘plam yashil deb aytilmaydi.
- Jonli READ ONLY smoke 11:28 Toshkent: yangi GPS va ETA SQL so‘rovlari bajarildi;
  tekshirilgan tranzaksiyada `transaction_read_only=on`.
  Bir transportning 1 soatlik GPS tarixi yetarli bo‘lmagani uchun ball berilmadi.
  500 faol/rejadagi reys va 3 054 tarixiy reys ko‘rildi; ma’lumot shartlari sabab ETA berilmadi.
  Kesilgan ro‘yxat va barcha sabablar natijada qaytdi.
- Dalil `.codex_run/intelligence_smoke.json`; backend muammolari
  [BACKEND_INTEGRATION.md](BACKEND_INTEGRATION.md)da.
- Modelning real aniqligi, real safarda ETA xatosi va risk chegaralari kalibrlanmagan.
  Brauzerda vizual QA bajarilmadi; DOM testi vizual tekshiruv o‘rniga da’vo qilinmaydi.
- ATIL bazasiga yozuv, avtomatik jarima, haydovchini bloklash, transport biriktirish
  yoki tashqi xabar yuborish bajarilmaydi. Avtomatik yangi hisoblar standartda o‘chiq.

## Asosiy dispetcher — 2026-11-01

- Tegishli Python regressiya va yangi integratsiya testlari: **383 passed**.
- JavaScript UI testi: 11 bo‘lim, qiymat yo‘qligi, HTML escaping, login
  xatolari, fon hisobining progress/tayyor holati va bo‘sh reja — o‘tdi.
- Eski GPS frontend regressiya testi — o‘tdi.
- Barcha Python modullari compile tekshiruvi va JS syntax tekshiruvi — o‘tdi.
- `main:app` importi va `/ai-dispatcher/api/dashboard` ro‘yxatdan o‘tishi — o‘tdi.
- Haqiqiy lokal HTTP server: HTML, JS, autentifikatsiya, saqlangan hisobot,
  uchta fon ish turi va dasturchi hisoboti eksporti — o‘tdi.
- Jonli PostgreSQL snapshot (20:10 Toshkent vaqti): 161 transport,
  254 haydovchi, 452 kutayotgan ariza, 304 faol reys, 70 GPS bog‘lanishi.
  Snapshot bo‘limlarida so‘rov xatosi bo‘lmadi. Bular tekshiruv paytidagi
  qiymatlar, keyin o‘zgarishi tabiiy.
- Jonli tanlash: DUMP_TRUCK uchun 13 transport ko‘rildi, 4 transport
  cheklovlardan o‘tdi, shu kundagi shartlardan o‘tgan haydovchi topilmadi.
- Jonli reja: 200 ariza tekshirildi; 199 koordinatasiz, 1 mos transportsiz.
  Bajarilmagan reja muvaffaqiyatli biriktirish deb ko‘rsatilmadi.
- Bitta haqiqiy ariza bo‘yicha LLM izohi: `COMPLETE`, `source=llm`;
  bajarish holati `NOT_SENT`. Modelning barcha mumkin bo‘lgan javoblari
  tekshirilgan degani emas.
- Saqlangan dalillar: loyiha ildizidagi `.codex_run/dispatch_live_smoke.json`
  va `.codex_run/dispatch_ai_smoke.json`.

Brauzer runtime’ida mavjud browserlar ro‘yxati bo‘sh bo‘ldi. Shuning uchun
desktop/mobile screenshot va haqiqiy brauzerdagi vizual QA bajarilmadi.
DOM harness va HTTP testlari shu tekshiruvning o‘rnini bosadi deb aytilmaydi.

ATIL bazasiga yozish, tashqi webhook orqali bajarish, haqiqiy transportni
biriktirish yoki xabarni tashqi odamga yuborish bu tekshiruvda bajarilmadi.

## Rahbariyat taqdimoti — 2026-11-02

- 15 slayd va har birida nutq matni; loyiha kodi/hujjatlari manba sifatida qayd etilgan.
- `presentation/ATIL_AI_TAQDIMOT.html` bir faylda yig‘ildi; tashqi CSS, JS,
  shrift yoki ma’lumot so‘rovi talab qilinmaydi. Ko‘rgazmali ma’lumotlar
  va 2026-11-01 audit sonlari tegishli belgi/sana bilan berilgan.
- HTML tuzilishi, yagona IDlar, ARIA havolalari, barcha slayd va nutq matnlari tekshirildi.
- HTTP: taqdimot, CSS/JS, yuklab olish, CSP, fayllar allowlisti va API auth — o‘tdi.
  TestClient lifespan ishga tushirilmadi: baza va jadvalga murojaat bo‘lmadi.
- JS DOM harness: slaydlar, klaviatura, mazmun/nutq dialoglari, to‘rt bosqichli
  misol, jadval namunasi, print chaqiruvi va hash navigatsiyasi — o‘tdi.
- Mavjud dispetcher integratsiya testlari: **21 passed**; mavjud 11 bo‘limli
  frontend regressiya testi — o‘tdi. Pytest cache yozuvi ruxsat ogohlantirishini berdi;
  testlar muvaffaqiyatli yakunlandi.
- Brauzer sessiyasi mavjud emas: desktop/mobile vizual tekshiruv, to‘liq ekran
  va haqiqiy PDF render natijasi tekshirilmagan. DOM/HTTP tekshiruvi vizual QA emas.
- Qayta tekshirish skriptlari: `.codex_run/check_dispatch_presentation.py`
  va `.codex_run/check_dispatch_presentation.cjs` (loyiha ildiziga nisbatan).
