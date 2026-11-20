# Haydash xavfsizligi, risk, ETA va kechikish

Bu modul beshta vazifani ikkita saqlanadigan fon hisobida bajaradi:

| Vazifa | UI | Natija |
|---|---|---|
| Tezlik oshirish | Haydash xavfsizligi | Davr, maksimal tezlik, operator kiritgan limit, GPS manba nuqtalari |
| Haydovchi risk indeksi | Haydash xavfsizligi | Haydovchi–transport juftligi va kuzatilgan davr uchun 0–100; yetarli dalil bo‘lmasa `null` |
| Keskin tormozlash, tezlanish, burilish | Haydash xavfsizligi | Yuqori chastotali GPSdan hisobiy hodisalar, m/s² va vaqt |
| ETA | ETA va kechikish | Tarixiy davomiylik medianasi, 10–90 percentil oralig‘i, tarix soni |
| Kechikish | ETA va kechikish / Xabarlar | Reja vaqti o‘tgan / kechikish kutilmoqda / mumkin / tarixiy oraliqqa sig‘adi / noma’lum |

## Ishlatish

1. Asosiy ilovada `/ai-dispatcher/` manziliga kiring. Yangi bo‘limlar uchun sahifani yangilang.
2. **Haydash xavfsizligi** bo‘limida transport yoki barcha GPS transportlarini, oxirgi soatlar sonini tanlang.
3. Korxona tezlik chegarasi va pilot mezonlarni tekshiring. Limit bo‘sh bo‘lsa tezlik bo‘yicha baho berilmaydi.
4. **Hisoblash** tugmasini bosing. Natija dialogda, keyinchalik **Hisobotlar tarixi**da ochiladi; JSON eksport saqlanadi.
5. **ETA va kechikish** bo‘limida prognozni ishga tushiring. Eski zonasiz ustunlar zonasini faqat backend tasdiqlagach tanlang.
6. Avtomatik ishlashi uchun kerakli bo‘limda **Parametrlarni saqlash**, so‘ng **Avtomatik jadval**da umumiy jadval va xavfsizlik / ETA bayroqlarini yoqing.

Jadval standartda o‘chiq. Server ishlasa, brauzer yopiq paytda ham fon hisoblari bajariladi.
Saqlangan monitoring oralig‘ida yangi hisob navbatga qo‘yiladi; qayta ishga tushganda bir vaqt oralig‘i ikki marta navbatga tushmaydi.
Xavfsizlik uchun davr har safar joriy vaqtda tugaydi. UI navbat holatini 5 soniyada yangilaydi.
Xavfsizlik hodisalari transport/tur/kun bo‘yicha, ETA xabarlari reys/reja-vaqti/ogohlantirish darajasi bo‘yicha takrorlanmaydi.
Avtomatik hisobda LLM ishlatilmaydi; qo‘lda uning izohini yoqish mumkin. Hisoblar LLMga bog‘liq emas.

## Hisoblash shartlari

- `gps_archive_point` → `vehicle_gps.provider_connection`. BEPULGPS `speed` knots → km/soat × 1.852. Noma’lum provayder birligi taxmin qilinmaydi; mavjud `FY_ARCHIVE_SPEED_UNITS` sozlamasi ishlatiladi.
- `valid=true`, yaroqli koordinata, sonli 0–200 km/soat tezlik talab qilinadi. Jismonan mumkin bo‘lmagan koordinata sakrashi, ziddiyatli bir vaqtdagi nuqtalar va binding almashishi intervalni uzadi.
- Tezlik uchun qo‘shni nuqtalar oralig‘i ko‘pi bilan 120 s; ikkala uchida ham limit+toleransdan yuqori bo‘lishi kerak. Kamida 10 s yig‘ilgan intervallar hodisa sifatida chiqadi. Bu interval ichidagi barcha soniyalarni uzluksiz o‘lchash emas, GPSdan hisobiy baho.
- Haydovchi faqat intervalni qoplaydigan haqiqiy yo‘l varaqasi yoki zonali reys boshlanish/tugash tarixi bilan aniqlanadi. Bir-biriga zid yoki noma’lum haydovchi biriktirishi ballni bloklaydi. `assigned_driver_id` va joriy GPS haydovchisi tarix o‘rniga ishlatilmaydi.
- Tormoz/tezlanish: `Δspeed / 3.6 / Δseconds`. Burilish: o‘rtacha tezlik × burchak o‘zgarishi / vaqt. Burchak 359°→1° to‘g‘ri o‘raladi. Oraliq ko‘pi bilan 2 s; burilish uchun `course` va ikki nuqtada kamida 5 km/soat talab qilinadi.
- Standart keskin harakat chegaralari 3 m/s² — **pilot qiymatlar**, korxona siyosati yoki qonuniy norma emas. UI orqali o‘zgartiriladi. Ketma-ket bir xil keskin hodisa birlashtiriladi.
- Standart risk **faqat tezlik indeksi**: `100 × Σ(min(1,(o‘rtacha tezlik−limit−tolerans)/limit) × interval) / kuzatilgan harakat soniyalari`. Faqat limitdan yuqori intervallar suratga qo‘shiladi. Kamida 15 daqiqalik haydovchiga biriktirilgan kuzatilgan harakat talab qilinadi. 10 soniyadan qisqa oshirish intervali indeksda qatnashadi, hodisalar ro‘yxatida chiqmasligi mumkin.
- Keskin harakatni ballga qo‘shish yoqilsa: 50% tezlik indeksi + 50% `min(100,100 × hodisa/soat / sozlangan 100-ball chastotasi)`. Yuqori chastotali va yo‘nalishi bor interval qamrovi kamida 90% bo‘lishi shart. Qolgan kuzatilmagan intervalda hodisalar noma’lum. Umumiy haydovchi reytingi yoki avariya ehtimoli deyilmaydi.
- ETA `trip.actual_arrival_at − actual_departure_at` tarixidan olinadi. `release_return_instant` yoki yo‘l varaqasi qaytish vaqti yetib kelish o‘rniga ishlatilmaydi. Bir xil marshrut va transport turi/ish rejimi; yetmasa, manzil IDlari + transport turi + ish rejimi + safar turi bir xil bo‘lgan guruh ishlatiladi.
- Tarixda faqat `COMPLETED`, 1 daqiqa–72 soat davomiylik va 180 kunlik (sozlanadi) yakunlangan reyslar. Kelajakdagi yakun va joriy reys chiqariladi. Zonasi yo‘q tarixda UTC/Toshkent noaniqligi uchun eng kech UTC talqini olinadi; juft vaqtlar farqida bir xil offset bekor bo‘ladi. Bu tarixiy ikki ustun bir xil vaqt konvensiyasida yozilgan degan faraz; backend tasdig‘i kerak.
- Yo‘ldagi safar uchun allaqachon o‘tgan vaqtdan uzun tarixlar qoladi. Kamida 5 ta mos kuzatuv kerak; yetmasa ETA yo‘q. Jo‘namagan reysda boshlash `max(reja, hozir)` deb faraz qilinadi va UI buni ko‘rsatadi.
- Faol reysning zonali jo‘nash/reja vaqtlariga ustuvorlik beriladi; eski vaqtlar faqat operator zona tanlasa ishlatiladi. Vaqt ziddiyatlari, kelajakdagi haqiqiy jo‘nash va yakunlanganlik belgisi prognozni bloklaydi.
- ETA modeli tirbandlik, ob-havo, qolgan geografik masofa, yuklash navbati yoki haydovchi tanaffusini hozircha hisoblamaydi. 10–90 percentil — tarix tarqalishi, kalibrlangan 80% ishonch intervali emas.

## Baza va resurs chegaralari

ATILga faqat `READ ONLY` tranzaksiyalar; har SQLga 10 s limit. Yangi jadvallar yaratilmaydi.
Sozlamalar, vazifalar va xabarlar mavjud lokal SQLite saqlash mexanizmida qoladi.
GPS: indekslangan `(vehicle_id, fix_time)` orqali, ko‘pi bilan 200 transport, 5 000 nuqta/transport, jami 50 000 nuqta.
Yig‘ish vaqt budjeti 60 s (oxirgi so‘rovning timeoutigacha qo‘shimcha vaqt bo‘lishi mumkin).
Limitdan kesilgan transportda risk balli berilmaydi; davrni qisqartirish yoki transportni tanlash kerak.
Biriktirish tarixi 10 000; kesilsa barcha haydovchi ballari bloklanadi. Hodisalar UI ro‘yxati 1 000 bilan chegaralangan;
transport ichidagi hodisalar va to‘liq natija JSONda saqlanadi.
ETA: 500 faol/rejadagi reys, 10 000 tarixiy reys. Tarix kesilsa prognoz berilmaydi; tarix kunlarini qisqartiring.
Manba xatosi bo‘sh natija sifatida yashirilmaydi. Ushbu limitlar sabab butun parkni yuqori chastotada uzoq davr bo‘yicha tahlil qilish uchun kelgusida oqimli agregatsiya kerak bo‘ladi.

## API

Mavjud HTTP Basic himoyali `POST /ai-dispatcher/api/jobs` orqali:

```json
{"kind":"safety","analyze":false,"safety":{"hours":24,"policy":{"name":"Korxona-v1","speed_limit_kph":60}}}
```

```json
{"kind":"eta","analyze":false,"eta":{"minimum_samples":5,"lookback_days":180}}
```

`safety`/`eta` parametrlari berilmasa saqlangan sozlama olinadi. Natija mavjud `GET /jobs/{id}`da.
`PUT /settings`: `auto_safety`, `auto_eta`, `safety`, `eta` qo‘shildi; eski klientlar uchun standartlar orqaga mos.
PATCH emas: UI boshqa sozlamalarni saqlagan holda to‘liq PUT yuboradi.

## Tekshirish

`python -m pytest tests/test_dispatch_intelligence.py tests/test_ai_dispetcher.py -q`

`node tests/test_ai_dispetcher_frontend.cjs`
