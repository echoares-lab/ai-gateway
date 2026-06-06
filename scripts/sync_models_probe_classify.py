"""Classify sync-models probe HTTP responses for litellm-config.yaml reconciliation."""

from __future__ import annotations

import json
import sys
from typing import Any

# Outcomes consumed by cliproxy-setup.sh probe_model / cmd_sync_models.
OUTCOME_SUCCESS = "success"
OUTCOME_TRANSIENT = "transient"
OUTCOME_MISSING_MODEL = "missing_model"
OUTCOME_PRESERVE = "preserve"

TRANSIENT_HTTP = frozenset({408, 425, 429, 500, 502, 503, 504, 529})
RATE_LIMIT_KEYWORDS = (
    "429",
    "rate limit",
    "rate_limit",
    "rate-limited",
    "ratelimit",
    "quota",
    "cooldown",
    "too many requests",
    "resource exhausted",
    "resource_exhausted",
    "capacity",
    "overloaded",
    "temporarily unavailable",
    "try again",
)
MISSING_MODEL_KEYWORDS = (
    "model not found",
    "model_not_found",
    "does not exist",
    "unknown model",
    "invalid model",
)


def _body_dict(body: str) -> dict[str, Any] | None:
    if not body.strip():
        return None
    try:
        parsed = json.loads(body)
    except json.JSONDecodeError:
        return None
    return parsed if isinstance(parsed, dict) else None


def _body_text(body: str) -> str:
    data = _body_dict(body)
    if data is None:
        return body.lower()
    parts: list[str] = []
    err = data.get("error")
    if isinstance(err, dict):
        for key in ("message", "type", "code"):
            val = err.get(key)
            if val is not None:
                parts.append(str(val))
    elif err is not None:
        parts.append(str(err))
    parts.append(json.dumps(data))
    return " ".join(parts).lower()


def _has_keyword(text: str, keywords: tuple[str, ...]) -> bool:
    lowered = text.lower()
    return any(keyword in lowered for keyword in keywords)


def probe_exit_code(outcome: str) -> int:
    """Map classify outcome to cliproxy-setup.sh probe_model exit code."""
    if outcome == OUTCOME_SUCCESS:
        return 0
    if outcome == OUTCOME_MISSING_MODEL:
        return 44
    return 42


def should_remove_model_from_config(probe_exit_code: int) -> bool:
    """True only when sync-models legacy path may delete a model block."""
    return probe_exit_code == 44


def remove_model_block_from_litellm_config(path: str, alias: str) -> None:
    """Remove one model_name block — mirrors cliproxy-setup.sh cmd_sync_models_legacy."""
    import re

    with open(path, encoding="utf-8") as handle:
        txt = handle.read()
    pattern = (
        rf"\n  - model_name: {re.escape(alias)}\n"
        r"    litellm_params:.*?(?=\n  - model_name:|\ngeneral_settings:)"
    )
    txt = re.sub(pattern, "", txt, flags=re.DOTALL)
    with open(path, "w", encoding="utf-8") as handle:
        handle.write(txt)


def classify_probe_response(http_code: str, body: str = "") -> str:
    """Return probe outcome used to decide whether to remove a model from config."""
    if not http_code or not str(http_code).isdigit():
        return OUTCOME_TRANSIENT

    code = int(http_code)
    if code == 0:
        return OUTCOME_TRANSIENT
    text = _body_text(body)

    if _has_keyword(text, RATE_LIMIT_KEYWORDS):
        return OUTCOME_TRANSIENT

    if code == 404 or _has_keyword(text, MISSING_MODEL_KEYWORDS):
        return OUTCOME_MISSING_MODEL

    if code == 429 or code in TRANSIENT_HTTP:
        return OUTCOME_TRANSIENT

    if code in (401, 403):
        return OUTCOME_PRESERVE

    if 200 <= code < 300:
        data = _body_dict(body)
        if data is None:
            return OUTCOME_PRESERVE
        choices = data.get("choices")
        if isinstance(choices, list) and choices:
            return OUTCOME_SUCCESS
        if data.get("error"):
            return OUTCOME_TRANSIENT if _has_keyword(text, RATE_LIMIT_KEYWORDS) else OUTCOME_PRESERVE
        return OUTCOME_PRESERVE

    if code >= 400:
        return OUTCOME_PRESERVE

    return OUTCOME_PRESERVE


def main() -> int:
    http_code = sys.argv[1] if len(sys.argv) > 1 else ""
    body = sys.stdin.read()
    print(classify_probe_response(http_code, body))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
