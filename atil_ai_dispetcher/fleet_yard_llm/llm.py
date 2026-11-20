"""Mavjud vLLM/Ollama klienti orqali structured JSON tahlili."""

from __future__ import annotations

import sys
from pathlib import Path
from typing import Any

from atil_ai_dispetcher.fleet_yard_llm import config

_CHATBOT_DIR = str(Path(__file__).resolve().parents[2] / "atil_chatbot")
if _CHATBOT_DIR not in sys.path:
    sys.path.insert(0, _CHATBOT_DIR)


def model_info() -> dict[str, str]:
    from config import MODEL_NAME, USE_VLLM

    return {"provider": "vllm" if USE_VLLM else "ollama", "model": MODEL_NAME}


async def ask(prompt: str, *, json_schema: dict[str, Any]) -> str:
    from config import DEFAULT_NUM_CTX
    from ollama_client import ask_llm

    return await ask_llm(prompt, {
        "timeout": config.LLM_TIMEOUT_SECONDS,
        "options": {
            "temperature": 0.1, "num_predict": config.AI_MAX_TOKENS,
            "num_ctx": DEFAULT_NUM_CTX,
        },
        "think": False,
        "response_json_schema": json_schema,
    })
