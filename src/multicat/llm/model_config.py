from __future__ import annotations

import os


DEFAULT_OPENROUTER_MODEL = "openai/gpt-4.1-mini"

AGENT_MODEL_ENV_KEYS = {
    "screening": "OPENROUTER_SCREENING_MODEL",
    "extraction": "OPENROUTER_EXTRACTION_MODEL",
    "judge": "OPENROUTER_JUDGE_MODEL",
    "repair": "OPENROUTER_REPAIR_MODEL",
    "plot": "OPENROUTER_PLOT_MODEL",
}


def model_for_agent(agent_kind: str) -> str:
    env_key = AGENT_MODEL_ENV_KEYS.get(agent_kind)
    if env_key:
        model = os.environ.get(env_key)
        if model:
            return model
    return os.environ.get("OPENROUTER_MODEL", DEFAULT_OPENROUTER_MODEL)
