from typing import Any
import os
import httpx
import logging
import json

log = logging.getLogger("gateway-engine.onboarding_service")

class OnboardingService:
    def __init__(self):
        # Configuration for LiteLLM admin API
        self.litellm_admin_url = os.environ.get("LITELLM_ADMIN_URL", "http://litellm:4000").rstrip("/")
        self.litellm_master_key = os.environ.get("LITELLM_MASTER_KEY", "").strip()
        self.admin_api_key = os.environ.get("ADMIN_API_KEY", "").strip()

    async def register_tenant(self, tenant_id: str, email: str, plan_id: str = "default") -> dict[str, Any]:
        """
        Registers a new tenant by:
        1. Creating a LiteLLM team.
        2. Generating an API key for the team.
        3. Initializing budget/quota based on the plan.
        """
        log.info(f"Registering new tenant: {tenant_id}, email: {email}, plan: {plan_id}")

        if not self.litellm_master_key:
            log.error("LITELLM_MASTER_KEY is not configured.")
            return {"success": False, "error": "LITELLM_MASTER_KEY not configured"}
        if not self.admin_api_key:
            log.error("ADMIN_API_KEY is not configured.")
            return {"success": False, "error": "ADMIN_API_KEY not configured"}

        headers = {"Authorization": f"Bearer {self.litellm_master_key}"}
        # Step 1: Create LiteLLM team
        team_creation_url = f"{self.litellm_admin_url}/team/new"
        team_payload = {"team_name": tenant_id}
        try:
            async with httpx.AsyncClient() as client:
                team_resp = await client.post(team_creation_url, json=team_payload, headers=headers)
                team_resp.raise_for_status()
                team_data = team_resp.json()
                team_id = team_data.get("team_id")
                log.info(f"Team '{tenant_id}' created with ID: {team_id}")
        except httpx.HTTPStatusError as e:
            log.error(f"Failed to create team {tenant_id}: {e.response.text}")
            return {"success": False, "error": f"Failed to create team: {e.response.text}"}
        except httpx.RequestError as e:
            log.error(f"Network error while creating team {tenant_id}: {e}")
            return {"success": False, "error": f"Network error creating team: {e}"}

        # Step 2: Generate API key for the team
        key_generation_url = f"{self.litellm_admin_url}/key/generate"
        key_payload = {
            "team_id": team_id,
            "key_name": f"{tenant_id}-api-key",
            "max_budget": 0, # To be updated by policy engine or further steps
            "budget_duration": "monthly"
        }
        try:
            async with httpx.AsyncClient() as client:
                key_resp = await client.post(key_generation_url, json=key_payload, headers=headers)
                key_resp.raise_for_status()
                key_data = key_resp.json()
                api_key = key_data.get("key")
                log.info(f"API key generated for team {tenant_id}")
        except httpx.HTTPStatusError as e:
            log.error(f"Failed to generate API key for team {tenant_id}: {e.response.text}")
            return {"success": False, "error": f"Failed to generate API key: {e.response.text}"}
        except httpx.RequestError as e:
            log.error(f"Network error while generating API key for team {tenant_id}: {e}")
            return {"success": False, "error": f"Network error generating API key: {e}"}

        # Step 3: Integrate with Policy Engine for budget/quota enforcement (placeholder for now)
        # This will be done in a later stage, leveraging existing policy engine mechanisms.
        log.info(f"Tenant {tenant_id} registered successfully.")
        return {"success": True, "tenant_id": tenant_id, "api_key": api_key, "team_id": team_id}

onboarding_service = OnboardingService()
