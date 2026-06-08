import yaml
from pathlib import Path
from typing import Any

PROFILES_DIR = Path(__file__).parent / "profiles"

class ClientDetector:
    def __init__(self):
        self.profiles = []
        for profile_file in PROFILES_DIR.glob("*.yaml"):
            if profile_file.name == "schema.yaml":
                continue
            with open(profile_file, "r") as f:
                self.profiles.append(yaml.safe_load(f))

    def detect(self, request: Any) -> dict | None:
        user_agent = request.headers.get("user-agent", "")
        for profile in self.profiles:
            sig = profile.get("signature", {})
            if sig.get("user_agent_contains") in user_agent:
                return profile
        return None

client_detector = ClientDetector()
