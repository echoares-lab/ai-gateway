"""Restart LiteLLM whenever litellm-config.yaml changes on disk."""
import http.client
import logging
import os
import socket
import time
from watchfiles import watch, Change

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


def _restart():
    """Send restart signal to LiteLLM container via Docker Engine API."""
    c = _UnixHTTP()
    c.request("POST", f"/containers/{CONTAINER}/restart?t=10")
    r = c.getresponse()
    r.read()
    c.close()
    if r.status in (204, 200):
        log.info("Restarted %s (HTTP %d)", CONTAINER, r.status)
    else:
        log.error("Docker restart HTTP %d for %s", r.status, CONTAINER)


def _only_modified(ch: Change, _: str) -> bool:
    """Filter to only detect file modifications, not attribute changes."""
    return ch == Change.modified


log.info("Watching %s — will restart %s on change", CONFIG, CONTAINER)
for _ in watch(CONFIG, watch_filter=_only_modified):
    log.info("Change detected, restarting LiteLLM…")
    time.sleep(0.5)  # debounce: some editors write in two steps
    _restart()
