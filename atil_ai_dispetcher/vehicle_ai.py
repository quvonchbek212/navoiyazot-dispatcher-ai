"""Single-vehicle GPS and garage AI analysis with deterministic facts."""

from __future__ import annotations

import asyncio
from bisect import bisect_left
from copy import deepcopy
import json
import logging
from pathlib import Path
import re
import sys

from pydantic import BaseModel, ConfigDict, Field, ValidationError

from . import config, garage

log = logging.getLogger(__name__)

_CHATBOT_DIR = str(Path(__file__).resolve().parents[1] / 'atil_chatbot')
_FORBIDDEN_CLAIM_RE = re.compile(
    r"jarima|o['‘’ʻʼ]?g['‘’ʻʼ]?ir|aybdor|ishlamagan|bekor\s+(?:turibdi|yotibdi)"
    r"|qurilma\s+buzil|tirband|nosoz|\byo['‘’ʻʼ]?l(?:da|dagi)\b|foiz",
    re.I,
)
_LLM_TIMEOUT_SECONDS = config.LLM_TIMEOUT
_LLM_MAX_TOKENS = 700


class Insight(BaseModel):
    model_config = ConfigDict(extra='forbid')
    code: str
    text: str = Field(min_length=8, max_length=360)
    evidence_ids: list[str] = Field(min_length=1, max_length=4)


class Answer(BaseModel):
    model_config = ConfigDict(extra='forbid')
    overview: str = Field(min_length=15, max_length=700)
    overview_evidence_ids: list[str] = Field(min_length=1, max_length=4)
    findings: list[Insight] = Field(min_length=1, max_length=4)
    actions: list[Insight] = Field(min_length=1, max_length=4)


def speed_metrics(history, start, end):
    """Calculate single-vehicle speed metrics strictly from connected GPS points."""
    points, barriers, _ = garage.normalize_observations(history.get('points', []), start, end)
    speeds = [p['speed_kph'] for p in points if p.get('speed_kph') is not None]
    moving_meters = 0.0
    moving_seconds = 0.0
    for a, b in zip(points, points[1:]):
        seconds = (b['time'] - a['time']).total_seconds()
        index = bisect_left(barriers, a['time'])
        if seconds > garage.MAX_GAP_SECONDS or (index < len(barriers) and barriers[index] <= b['time']):
            continue
        sa, sb = a.get('speed_kph'), b.get('speed_kph')
        if sa is not None and sb is not None and min(sa, sb) > 1:
            moving_meters += garage.distance(a, b)
            moving_seconds += seconds
    return {
        'last_speed_kph': points[-1].get('speed_kph') if points else None,
        'max_speed_kph': round(max(speeds), 1) if speeds else None,
        'avg_moving_speed_kph': round((moving_meters / 1000) / (moving_seconds / 3600), 1) if moving_seconds > 0 else None,
        'speed_points': len(speeds),
    }


def _coverage_percent(report, obs):
    start = report.get('period', {}).get('start')
    end = report.get('period', {}).get('end')
    observed = obs.get('observed_minutes')
    if not start or not end or observed is None or end <= start:
        return None
    total_minutes = (end - start).total_seconds() / 60
    return round(min(100.0, observed / total_minutes * 100), 1) if total_minutes > 0 else None


def facts(report, history, garage_item=None):
    """Build compact privacy-safe facts without plate numbers or raw coordinates."""
    obs = report.get('observation') or {}
    g = report.get('garage_view') or {}
    period = report.get('period') or {}
    hours = round((period['end'] - period['start']).total_seconds() / 3600, 1) if period.get('start') and period.get('end') else None
    stops = (garage_item or {}).get('stops') or []
    return [
        {
            'id': 'F.period',
            'meaning': 'Tanlangan davr, GPS manbasi va tarix to‘liqligi',
            'value': {
                'hours': hours,
                'source': history.get('source', 'ATIL_API'),
                'fallback_reason': report.get('fallback_reason'),
                'complete': bool(report.get('complete')),
            },
        },
        {
            'id': 'F.gps',
            'meaning': 'Yaroqli GPS nuqtalari va signal uzilishlari',
            'value': {
                'points': obs.get('points', 0),
                'signal_gaps': obs.get('signal_gaps'),
                'coverage_percent': _coverage_percent(report, obs),
                'rejected_points': obs.get('rejected', 0),
                'first_signal_at': obs.get('first_signal_at'),
                'last_signal_at': obs.get('last_signal_at'),
            },
        },
        {
            'id': 'F.movement',
            'meaning': 'Kuzatilgan masofa, harakat va umumiy to‘xtash davomiyligi',
            'value': {
                'distance_km': obs.get('distance_km'),
                'observed_moving_minutes': obs.get('observed_moving_minutes'),
                'observed_stop_minutes': obs.get('observed_stop_minutes'),
                'observed_minutes': obs.get('observed_minutes'),
            },
        },
        {
            'id': 'F.speed',
            'meaning': 'Kuzatilgan tezlik ko‘rsatkichlari (km/soat)',
            'value': {
                'last_speed_kph': obs.get('last_speed_kph'),
                'max_speed_kph': obs.get('max_speed_kph'),
                'avg_moving_speed_kph': obs.get('avg_moving_speed_kph'),
                'speed_points': obs.get('speed_points', 0),
            },
        },
        {
            'id': 'F.garage',
            'meaning': 'Garaj zonasi holati, kirish-chiqish va to‘xtash vaqti',
            'value': {
                'state': g.get('state', 'NOT_CONFIGURED'),
                'is_example': bool(g.get('is_example')),
                'entries': g.get('entries'),
                'exits': g.get('exits'),
                'garage_stop_minutes': g.get('stop_minutes'),
                'outside_stop_minutes': g.get('outside_stop_minutes'),
                'long_stops_count': len(stops) if g.get('entries') is not None else None,
                'active_long_stop': bool((garage_item or {}).get('active_long_stop')) if g.get('entries') is not None else None,
            },
        },
    ]


def allowed(report, garage_item=None):
    """Restrict findings and actions strictly to what the facts actually observed."""
    obs = report.get('observation') or {}
    g = report.get('garage_view') or {}
    points = obs.get('points', 0)
    complete = bool(report.get('complete'))
    gaps = obs.get('signal_gaps') or 0
    moving = obs.get('observed_moving_minutes') or 0
    stopped = obs.get('observed_stop_minutes') or 0
    dist = obs.get('distance_km') or 0
    max_spd = obs.get('max_speed_kph')
    g_state = g.get('state', 'NOT_CONFIGURED')
    long_stops = len((garage_item or {}).get('stops') or [])
    outside_stop = g.get('outside_stop_minutes') or 0

    finding = {'DATA_LIMITATIONS': {'F.period', 'F.gps'}}
    action = {'DISPATCH_REVIEW': {'F.period', 'F.gps'}}
    if not points:
        finding['NO_GPS_DATA'] = {'F.period', 'F.gps'}
    if not complete or gaps or report.get('fallback_reason'):
        finding['PARTIAL_COVERAGE'] = {'F.period', 'F.gps'}
        action['CHECK_GPS'] = {'F.period', 'F.gps'}
    elif not points:
        action['CHECK_GPS'] = {'F.period', 'F.gps'}
    if dist > 0 or moving > 0:
        finding['MOVEMENT_SUMMARY'] = {'F.movement'}
        action['VERIFY_WAYBILL'] = {'F.movement'}
    if stopped > 0:
        finding['STOP_ACTIVITY'] = {'F.movement'}
    if stopped >= 30 or long_stops > 0 or outside_stop >= 15:
        action['REVIEW_STOPS'] = {'F.movement', 'F.garage'}
    if max_spd is not None:
        finding['SPEED_PROFILE'] = {'F.speed'}
        if max_spd >= 80:
            action['CHECK_SPEED'] = {'F.speed'}
    if g_state != 'NOT_CONFIGURED':
        finding['GARAGE_ACTIVITY'] = {'F.garage'}
    else:
        action['CONFIGURE_GARAGE'] = {'F.garage'}
    return finding, action


def _check_text(text):
    if re.search(r'[0-9%]', text):
        raise ValueError("Matnda raqam yoki foiz ishlatmang — sonlar kartochkalarda berilgan")
    if _FORBIDDEN_CLAIM_RE.search(text):
        raise ValueError("Tasdiqlanmagan sabab, jarima, nosozlik yoki tirbandlik iddaosi taqiqlanadi")


def response_schema(report, garage_item=None):
    schema = Answer.model_json_schema()
    findings, actions = allowed(report, garage_item)
    schema['properties']['overview']['pattern'] = '^[^0-9%]*$'
    for field, definition, codes in (('findings', 'Finding', findings), ('actions', 'Action', actions)):
        item = deepcopy(schema['$defs']['Insight'])
        item['properties']['code']['enum'] = sorted(codes)
        item['properties']['text']['pattern'] = '^[^0-9%]*$'
        item['properties']['evidence_ids']['items']['enum'] = sorted(set().union(*codes.values()))
        schema['$defs'][definition] = item
        schema['properties'][field]['items'] = {'$ref': '#/$defs/' + definition}
    del schema['$defs']['Insight']
    return schema


def validate(raw, report, history, garage_item=None):
    from core.ollama_json import extract_json

    try:
        output = Answer.model_validate(extract_json(raw))
    except ValidationError as exc:
        problems = ['.'.join(map(str, e['loc'])) + ': ' + e['msg'] for e in exc.errors()[:4]]
        raise ValueError('JSON shakli noto‘g‘ri: ' + '; '.join(problems)) from exc
    refs = {f['id'] for f in facts(report, history, garage_item)}
    if not set(output.overview_evidence_ids) <= refs:
        raise ValueError('Umumiy xulosada noma’lum dalil bor')
    _check_text(output.overview)
    findings, actions = allowed(report, garage_item)
    for rows, codes in ((output.findings, findings), (output.actions, actions)):
        for row in rows:
            if row.code not in codes or not set(row.evidence_ids) <= codes[row.code]:
                expected = ', '.join(sorted(codes.get(row.code, set())))
                raise ValueError(f'{row.code}: faqat shu dalillar ruxsat etilgan: {expected or "bu kod ruxsat etilmagan"}')
            _check_text(row.text)
    return output


def calculated(report, history, garage_item=None):
    """Deterministic fallback summary when the language model is unavailable."""
    obs = report.get('observation') or {}
    g = report.get('garage_view') or {}
    points = obs.get('points', 0)
    dist = obs.get('distance_km')
    moving = obs.get('observed_moving_minutes')
    stopped = obs.get('observed_stop_minutes')
    max_spd = obs.get('max_speed_kph')
    avg_spd = obs.get('avg_moving_speed_kph')
    g_state = g.get('state', 'NOT_CONFIGURED')

    findings, actions = [], []
    if not points:
        overview = 'Tanlangan davrda yaroqli GPS nuqtalari topilmadi. Bu transport ishlamaganini isbotlamaydi; signal va arxiv qamrovini tekshirish kerak.'
        findings.append({'code': 'NO_GPS_DATA', 'text': 'Tanlangan vaqt oralig‘ida yaroqli GPS signali qayd etilmadi.', 'evidence_ids': ['F.period', 'F.gps']})
        actions.append({'code': 'CHECK_GPS', 'text': 'Treker aloqasi, API ruxsati yoki kengroq vaqt oralig‘ini tekshiring.', 'evidence_ids': ['F.period', 'F.gps']})
    else:
        parts = [f"Tanlangan davrda {points} ta yaroqli GPS nuqtasi kuzatildi."]
        if dist is not None:
            parts.append(f"Kuzatilgan masofa {dist} km.")
        if moving is not None or stopped is not None:
            parts.append(f"Harakat {moving if moving is not None else 'noma’lum'} daqiqa, to‘xtash {stopped if stopped is not None else 'noma’lum'} daqiqa.")
        if max_spd is not None:
            parts.append(f"Maksimal tezlik {max_spd} km/soat" + (f", o‘rtacha harakat tezligi {avg_spd} km/soat." if avg_spd is not None else '.'))
        overview = ' '.join(parts)
        if not report.get('complete') or obs.get('signal_gaps') or report.get('fallback_reason'):
            findings.append({'code': 'PARTIAL_COVERAGE', 'text': f"Kuzatuv qisman olingan (signal uzilishlari: {obs.get('signal_gaps') or 0}).", 'evidence_ids': ['F.period', 'F.gps']})
            actions.append({'code': 'CHECK_GPS', 'text': 'GPS signalidagi bo‘shliqlar va ma’lumot manbasini tekshiring.', 'evidence_ids': ['F.period', 'F.gps']})
        if (dist or 0) > 0 or (moving or 0) > 0:
            findings.append({'code': 'MOVEMENT_SUMMARY', 'text': f"Transport harakati kuzatilgan ({dist if dist is not None else '—'} km).", 'evidence_ids': ['F.movement']})
            actions.append({'code': 'VERIFY_WAYBILL', 'text': 'Kuzatilgan masofa va harakat vaqtini faol yo‘l varaqasi yoki reys bilan solishtiring.', 'evidence_ids': ['F.movement']})
        if max_spd is not None:
            findings.append({'code': 'SPEED_PROFILE', 'text': f"Tezlik kuzatuvi mavjud (maksimal {max_spd} km/soat).", 'evidence_ids': ['F.speed']})
            if max_spd >= 80:
                actions.append({'code': 'CHECK_SPEED', 'text': 'Yuqori tezlik epizodlarini marshrut va yo‘l sharoiti bo‘yicha ko‘rib chiqing.', 'evidence_ids': ['F.speed']})
        if g_state != 'NOT_CONFIGURED':
            findings.append({'code': 'GARAGE_ACTIVITY', 'text': f"Garaj bo‘yicha kirish/chiqish: {g.get('entries') if g.get('entries') is not None else '—'} / {g.get('exits') if g.get('exits') is not None else '—'}.", 'evidence_ids': ['F.garage']})
            if (g.get('outside_stop_minutes') or 0) >= 15 or (garage_item or {}).get('stops'):
                actions.append({'code': 'REVIEW_STOPS', 'text': 'Garajdan tashqaridagi uzoq to‘xtashlar sababini dispetcherlik yozuvlari bilan tekshiring.', 'evidence_ids': ['F.movement', 'F.garage']})
        else:
            actions.append({'code': 'CONFIGURE_GARAGE', 'text': 'Garaj kirish-chiqishini kuzatish uchun garaj koordinatalarini sozlang.', 'evidence_ids': ['F.garage']})
    if not findings:
        findings.append({'code': 'DATA_LIMITATIONS', 'text': 'Faqat tasdiqlangan GPS kuzatuv oralig‘idagi ma’lumotlar hisobga olindi.', 'evidence_ids': ['F.period', 'F.gps']})
    if not actions:
        actions.append({'code': 'DISPATCH_REVIEW', 'text': 'Natijalarni joriy topshiriq va reys jadvali bilan solishtiring.', 'evidence_ids': ['F.period', 'F.gps']})
    return {
        'status': 'UNAVAILABLE',
        'source': 'calculated',
        'overview': overview,
        'findings': findings,
        'actions': actions,
        'evidence': facts(report, history, garage_item),
        'warning': None,
    }


def _model_info():
    if _CHATBOT_DIR not in sys.path:
        sys.path.insert(0, _CHATBOT_DIR)
    from config import MODEL_NAME, USE_VLLM

    return {'provider': 'vllm' if USE_VLLM else 'ollama', 'model': MODEL_NAME}


async def ask_model(prompt, *, json_schema):
    if _CHATBOT_DIR not in sys.path:
        sys.path.insert(0, _CHATBOT_DIR)
    from config import DEFAULT_NUM_CTX
    from ollama_client import ask_llm

    return await ask_llm(prompt, {
        'timeout': _LLM_TIMEOUT_SECONDS,
        'options': {'temperature': 0.1, 'num_predict': _LLM_MAX_TOKENS, 'num_ctx': DEFAULT_NUM_CTX},
        'think': False,
        'response_json_schema': json_schema,
    })


async def enrich(report, history, garage_item=None):
    """Run one grounded LLM analysis for a single vehicle's GPS and garage observation."""
    fallback = calculated(report, history, garage_item)
    catalog = facts(report, history, garage_item)
    allowed_findings, allowed_actions = allowed(report, garage_item)
    prompt = (
        "Siz avtopark dispetcherining tahlilchisisiz. O‘zbekcha JSON qaytaring.\n"
        "Berilgan bitta transportning GPS harakati, tezligi, to‘xtashlari va garaj kuzatuvini faqat dalillar asosida tushuntiring.\n"
        "Qoidalar:\n"
        "1. overview: 2-3 ta qisqa, amaliy jumla; findings: 2-3 ta asosiy holat; actions: 2-3 ta aniq tekshirish qadami.\n"
        "2. Matnda (overview va text ichida) raqam, foiz yoki sana YOZMANG — aniq sonlar ekrandagi kartochkalarda bor.\n"
        "3. Matnda evidence_id nomini yozmang; faqat evidence_ids massiviga joylang.\n"
        "4. Faqat ruxsat etilgan code va unga ruxsat etilgan evidence_ids dan foydalaning.\n"
        "5. GPS yo‘qligini yoki signal uzilishini 'ishlamagan', 'bekor turibdi' yoki 'qurilma buzilgan' demang.\n"
        "6. 'yo‘lda' so‘zi o‘rniga 'garajdan tashqarida' deb yozing; jarima, o‘g‘irlik, tirbandlik, nosozlik yoki haydovchi aybini o‘ylab topmang.\n"
        "7. Agar garaj namuna hudud bo‘lsa (is_example=true), buni eslating.\n"
        "JAVOBNING MAJBURIY JSON SHAKLI (barcha 4 ta asosiy kalit majburiy):\n"
        '{"overview":"Qisqa xulosa","overview_evidence_ids":["F.movement"],'
        '"findings":[{"code":"MOVEMENT_SUMMARY","text":"Kuzatuv izohi","evidence_ids":["F.movement"]}],'
        '"actions":[{"code":"VERIFY_WAYBILL","text":"Tekshirish tavsiyasi","evidence_ids":["F.movement"]}]}\n'
        "Bu faqat namuna shakl; mazmun, kod va dalillarni quyidagi haqiqiy dalillarga mos tanlang.\n"
        "DALILLAR VA RUXSAT ETILGAN KODLAR:\n"
        + json.dumps({
            'facts': catalog,
            'allowed_findings': {k: sorted(v) for k, v in allowed_findings.items()},
            'allowed_actions': {k: sorted(v) for k, v in allowed_actions.items()},
        }, ensure_ascii=False, default=str)
    )
    schema = response_schema(report, garage_item)
    try:
        async def attempt():
            nonlocal prompt
            for retry in range(2):
                raw = await ask_model(prompt, json_schema=schema)
                try:
                    return validate(raw, report, history, garage_item)
                except ValueError as exc:
                    if retry:
                        raise
                    prompt += f'\nXatoni tuzating: {str(exc)[:220]}. Raqamsiz to‘liq JSON qaytaring.'

        output = await asyncio.wait_for(attempt(), timeout=_LLM_TIMEOUT_SECONDS)
        return {
            'status': 'COMPLETE',
            'source': 'llm',
            'overview': output.overview,
            'findings': [r.model_dump() for r in output.findings],
            'actions': [r.model_dump() for r in output.actions],
            'evidence': catalog,
            'model': _model_info(),
            'warning': None,
        }
    except Exception as exc:
        log.warning('Vehicle GPS AI analysis unavailable: %s', type(exc).__name__)
        return {
            **fallback,
            'warning': 'AI javobi olinmadi yoki dalil tekshiruvidan o‘tmadi; hisoblangan tahlil ko‘rsatildi.',
        }
