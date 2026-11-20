"""Dispetcher yordamchisi — to'rtta alohida endpoint.

    GET /dispatcher/delayed     kechikayotgan reyslar
    GET /dispatcher/deviations  yo'nalishdan og'ayotgan mashinalar
    GET /dispatcher/idle        bekor turgan mashinalar
    GET /dispatcher/documents   hujjati tugayotgan haydovchi va mashinalar

NIMA UCHUN TO'RTTA, BITTA EMAS: har biri o'z ro'yxatini qaytaradi va
ro'yxatlar uzun. Bitta javobga yig'ilsa dispetcher kerakli narsani
qidirib o'tirardi, panel esa har bo'limni alohida yangilay olmasdi.
Har biri mustaqil chaqiriladi, o'z filtri va o'z limiti bilan.

Boshqa modullar kabi bu yerda ham `FastAPI()` yaratilmaydi — faqat
`APIRouter` beriladi.
"""
