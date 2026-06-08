import pytest
from core.policy.schemas import RoutingContext, TenancyContext

def test_tenancy_propagation_in_routing_context():
    """Verify that TenancyContext is correctly populated in RoutingContext."""
    tenancy_info = {
        "tenant_id": "echoares",
        "workspace_id": "core",
        "team_id": "eng",
        "repo_name": "ai-gateway",
        "environment": "dev"
    }
    
    # Simulate the RoutingContext construction with passed tenancy_info
    tenancy_context = TenancyContext(**tenancy_info)
    ctx = RoutingContext(
        requested_model="claude-sonnet",
        tenancy=tenancy_context
    )
    
    assert ctx.tenancy.tenant_id == "echoares"
    assert ctx.tenancy.team_id == "eng"
    assert ctx.tenancy.environment == "dev"
    print("Tenancy propagation test passed!")
