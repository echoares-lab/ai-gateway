# Token Usage Analytics for Admin Console

## Overview
This document outlines the implementation of granular token usage analytics for the admin console dashboard (#117). The feature provides detailed visibility into token consumption across providers, models, teams, and time periods.

## Requirements
1. **Per-provider token tracking**: Breakdown of input/output tokens by provider (Claude, GPT, Gemini, etc.)
2. **Per-model analytics**: Token consumption per model within each provider
3. **Time-based analysis**: Daily, weekly, and monthly token trends
4. **Cost attribution**: Calculate estimated costs based on current pricing
5. **Team/tenant breakdown**: Show usage per workspace/team when tenancy is available
6. **Rate limit warnings**: Alert when approaching provider quotas
7. **Historical data**: Retention of usage metrics for trend analysis

## Data Sources
- **Langfuse**: Trace-level token counts and latency metrics
- **LiteLLM logs**: Request-level input/output token counts
- **Translator metrics**: Prometheus metrics for request volume by provider/model
- **CPA-Manager**: Usage summaries from credential-prober

## Analytics Panel Schema
```json
{
  "status": "ok",
  "source": "langfuse:/api/traces + litellm:logs + translator:/metrics",
  "freshness_seconds": 300,
  "data": {
    "summary": {
      "total_input_tokens": 1250000,
      "total_output_tokens": 350000,
      "total_requests": 4500,
      "period": "2026-06-01 to 2026-06-05",
      "estimated_cost_usd": 8.45
    },
    "by_provider": [
      {
        "provider": "anthropic",
        "model_count": 7,
        "input_tokens": 600000,
        "output_tokens": 150000,
        "requests": 2100,
        "cost_usd": 4.20,
        "avg_input_tokens_per_request": 285
      }
    ],
    "by_model": [
      {
        "model": "claude-sonnet-4-6",
        "provider": "anthropic",
        "input_tokens": 350000,
        "output_tokens": 85000,
        "requests": 1200,
        "cost_usd": 2.45,
        "percentage_of_total": 28.5
      }
    ],
    "time_series": [
      {
        "date": "2026-06-01",
        "input_tokens": 280000,
        "output_tokens": 75000,
        "requests": 950,
        "cost_usd": 1.85
      }
    ],
    "warnings": [
      {
        "type": "approaching_quota",
        "provider": "gemini",
        "message": "Gemini Flash: 85% of daily quota used",
        "percentage_used": 85
      }
    ]
  }
}
```

## Implementation Phases
1. **Phase 1**: Add token tracking to translator and metrics aggregation
2. **Phase 2**: Implement Langfuse integration for detailed trace analytics
3. **Phase 3**: Add cost calculation layer with provider pricing
4. **Phase 4**: Time-series storage and historical analysis
5. **Phase 5**: Tenant/workspace-level breakdown

## API Endpoints
- `GET /admin/analytics/tokens/summary` - Overall token usage summary
- `GET /admin/analytics/tokens/by-provider` - Breakdown by provider
- `GET /admin/analytics/tokens/by-model` - Breakdown by model
- `GET /admin/analytics/tokens/time-series?start_date=&end_date=` - Historical trends

## Security Considerations
- All token usage endpoints require LiteLLM master key authentication
- No raw request data exposed; only aggregated metrics
- Cost estimates use publicly available pricing (no secrets)
- Tenant data filtered by operator permissions (when tenancy is available)

## Success Metrics
- Token counts accurate to within 1% of upstream provider APIs
- Dashboard load time under 2 seconds
- 95th percentile latency for analytics API under 500ms
- Retention of 90 days of historical data
