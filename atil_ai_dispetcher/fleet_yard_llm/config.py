"""Fleet yard resurs chegaralari. Garaj chegarasi so'rovda beriladi."""

from __future__ import annotations

import os
import json
from pathlib import Path

import pytz
from dotenv import load_dotenv

load_dotenv(Path(__file__).resolve().parents[2] / ".env")


def _integer(name: str, default: int, maximum: int) -> int:
    try:
        return max(1, min(int(os.getenv(name, str(default))), maximum))
    except ValueError:
        return default


TZ = pytz.timezone("Asia/Tashkent")
MAX_POINTS = _integer("FY_MAX_POINTS", 50000, 200000)
MAX_HISTORY_DAYS = _integer("FY_MAX_HISTORY_DAYS", 93, 93)
MAX_VEHICLES = _integer("FY_MAX_VEHICLES", 2000, 10000)
MAX_WORK_ROWS = _integer("FY_MAX_WORK_ROWS", 50000, 200000)
LLM_TIMEOUT_SECONDS = _integer("FY_LLM_TIMEOUT_SECONDS", 90, 180)
AI_TOTAL_TIMEOUT_SECONDS = _integer("FY_AI_TOTAL_TIMEOUT_SECONDS", 180, 300)
AI_MAX_TOKENS = _integer("FY_AI_MAX_TOKENS", 1600, 3000)
AI_CONCURRENCY = _integer("FY_AI_CONCURRENCY", 4, 8)
AI_MAX_VEHICLES = _integer("FY_AI_MAX_VEHICLES", 20, 50)
DEFAULT_LIMIT = min(_integer("FY_DEFAULT_LIMIT", 5, 50), AI_MAX_VEHICLES)
MONITOR_MAX_POINTS = _integer("FY_MONITOR_MAX_POINTS", 200000, 1000000)
MONITOR_DETAIL_LIMIT = 200

# BEPULGPS runs the Traccar Position API (verified against its public client).
# Position.speed is knots. Never infer a unit for an unknown connection.
ARCHIVE_SPEED_UNITS = {"BEPULGPS": "knots"}
for provider, unit in json.loads(os.getenv("FY_ARCHIVE_SPEED_UNITS", "{}")).items():
    if unit not in ("knots", "kph", "mph", "mps"):
        raise ValueError("FY_ARCHIVE_SPEED_UNITS: unit must be knots, kph, mph or mps")
    ARCHIVE_SPEED_UNITS[str(provider).upper()] = unit
MONITOR_PACKET_POINTS = _integer("FY_MONITOR_PACKET_POINTS", 4000, 20000)

