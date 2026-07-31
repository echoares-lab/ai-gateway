from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def test_claude_json_parse_boundary_is_typed() -> None:
    source = (ROOT / "services/gateway-engine/api/proxy_claude.py").read_text(encoding="utf-8")

    assert "except (json.JSONDecodeError, TypeError, ValueError):" in source


def test_request_body_model_extraction_boundary_is_typed() -> None:
    source = (ROOT / "services/gateway-engine/main.py").read_text(encoding="utf-8")

    assert "except (json.JSONDecodeError, TypeError, AttributeError):" in source
