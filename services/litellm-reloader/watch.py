"""Restart LiteLLM whenever litellm-config.yaml changes on disk,
performing offline pre-flight validation before triggering a restart.
"""

import http.client
import logging
import os
import socket
import time
from typing import Any

import yaml
from watchfiles import Change, watch

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger("litellm-reloader")

CONTAINER = os.environ.get("LITELLM_CONTAINER", "ai-litellm-1")
CONFIG = os.environ.get("CONFIG_PATH", "/config/litellm-config.yaml")
SOCK = "/var/run/docker.sock"


class _UnixHTTP(http.client.HTTPConnection):
    """HTTP client over Unix socket for Docker Engine API."""

    def __init__(self):
        super().__init__("localhost")

    def connect(self):
        s = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        s.connect(SOCK)
        self.sock = s


def _restart() -> bool:
    """Send restart signal to LiteLLM container via Docker Engine API."""
    log.info("Initiating restart of %s...", CONTAINER)
    c = _UnixHTTP()
    try:
        c.request("POST", f"/containers/{CONTAINER}/restart?t=10")
        r = c.getresponse()
        r.read()
        c.close()
        if r.status in (204, 200):
            log.info("Restarted %s (HTTP %d)", CONTAINER, r.status)
            return True
        else:
            log.error("Docker restart HTTP %d for %s", r.status, CONTAINER)
            return False
    except Exception as e:
        log.error("Failed to restart container %s: %s", CONTAINER, e)
        return False


def _config_content_changed(ch: Change, _: str) -> bool:
    """Detect content changes: edits and atomic file replace (delete + recreate)."""
    return ch in (Change.modified, Change.added)


# ---------------------------------------------------------------------------
# Pre-flight validation
# ---------------------------------------------------------------------------


def _validate_model_list(model_list: Any) -> list[str]:
    """Validate the model_list section.

    Returns a list of error strings (empty means valid).
    """
    errors: list[str] = []
    if not isinstance(model_list, list):
        errors.append(f"model_list must be a list, got {type(model_list).__name__}")
        return errors
    for idx, entry in enumerate(model_list):
        if not isinstance(entry, dict):
            errors.append(f"model_list[{idx}] must be a dict, got {type(entry).__name__}")
            continue
        if "model_name" not in entry:
            errors.append(f"model_list[{idx}] is missing required key 'model_name'")
        if "litellm_params" not in entry:
            errors.append(
                f"model_list[{idx}] (model_name={entry.get('model_name', '?')!r})"
                " is missing required key 'litellm_params'"
            )
    return errors


def _validate_mcp_servers(mcp_servers: Any) -> list[str]:
    """Validate the mcp_servers section.

    Supports both stdio servers (command/args) and SSE servers (url/transport).
    Returns a list of error strings (empty means valid).
    """
    errors: list[str] = []
    if not isinstance(mcp_servers, dict):
        errors.append(f"litellm_settings.mcp_servers must be a dict, got {type(mcp_servers).__name__}")
        return errors
    for name, cfg in mcp_servers.items():
        prefix = f"mcp_servers.{name}"
        if not isinstance(cfg, dict):
            errors.append(f"{prefix} must be a dict, got {type(cfg).__name__}")
            continue
        # Detect server type
        has_url = "url" in cfg
        has_command = "command" in cfg
        transport = cfg.get("transport", "")
        is_sse = has_url or transport == "sse"

        if is_sse:
            # SSE / HTTP MCP server
            url = cfg.get("url", "")
            if not isinstance(url, str) or not url.startswith(("http://", "https://")):
                errors.append(
                    f"{prefix}: SSE server 'url' must be a string starting with 'http://' or 'https://', got {url!r}"
                )
        elif has_command:
            # Stdio MCP server
            command = cfg.get("command")
            if not isinstance(command, str) or not command:
                errors.append(f"{prefix}: 'command' must be a non-empty string, got {command!r}")
            args = cfg.get("args")
            if args is not None:
                if not isinstance(args, list):
                    errors.append(f"{prefix}: 'args' must be a list, got {type(args).__name__}")
                elif not all(isinstance(a, str) for a in args):
                    errors.append(f"{prefix}: all elements in 'args' must be strings")
            env = cfg.get("env")
            if env is not None and not isinstance(env, dict):
                errors.append(f"{prefix}: 'env' must be a dict, got {type(env).__name__}")
        else:
            errors.append(f"{prefix}: MCP server must have either 'command' (stdio) or 'url' (SSE)")
    return errors


def validate_config(config_path: str) -> bool:
    """Run offline pre-flight checks on the LiteLLM config file.

    Returns True if the config is valid and a restart should proceed,
    False if the config has errors and the restart should be aborted.
    """
    log.info("Pre-flight: validating %s ...", config_path)
    try:
        with open(config_path, "r") as f:
            raw = f.read()
    except OSError as e:
        log.critical("Pre-flight: cannot read config file %s: %s", config_path, e)
        return False

    # 1. YAML syntax check
    try:
        data = yaml.safe_load(raw)
    except yaml.YAMLError as e:
        log.critical("Pre-flight: YAML syntax error in %s: %s", config_path, e)
        return False

    if not isinstance(data, dict):
        log.critical(
            "Pre-flight: config root must be a YAML mapping, got %s",
            type(data).__name__,
        )
        return False

    errors: list[str] = []

    # 2. model_list validation
    if "model_list" in data:
        errors.extend(_validate_model_list(data["model_list"]))

    # 3. mcp_servers validation (nested under litellm_settings)
    litellm_settings = data.get("litellm_settings", {})
    if isinstance(litellm_settings, dict) and "mcp_servers" in litellm_settings:
        errors.extend(_validate_mcp_servers(litellm_settings["mcp_servers"]))

    if errors:
        log.critical(
            "Pre-flight: %d validation error(s) in %s — aborting reload:",
            len(errors),
            config_path,
        )
        for err in errors:
            log.critical("  • %s", err)
        log.critical(
            "Pre-flight: configuration validation FAILED. "
            "Keeping previous configuration. LiteLLM will NOT be restarted."
        )
        return False

    log.info("Pre-flight: configuration is valid. Proceeding with restart.")
    return True


# ---------------------------------------------------------------------------
# Main watch loop
# ---------------------------------------------------------------------------


def main():
    log.info("Watching %s — will restart %s on change", CONFIG, CONTAINER)
    try:
        for _ in watch(CONFIG, watch_filter=_config_content_changed):
            log.info("Change detected in %s", CONFIG)
            time.sleep(0.5)  # debounce: some editors write in two steps
            if validate_config(CONFIG):
                _restart()
    except Exception as e:
        log.error("Error in watch loop: %s", e)


if __name__ == "__main__":
    main()
