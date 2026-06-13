# Routing and Failover Strategy

This document outlines the current routing and failover architecture of the AI Gateway, how it scales, potential improvements, and known limitations.

## 1. Current Routing Strategy

Requests flow through a two-level failover architecture:

```text
Client → LiteLLM (cross-MODEL fallback) → CLIProxy (cross-CREDENTIAL failover) → Provider OAuth
```

### CLIProxy: Credential-Level Failover (`fill-first` + `session-affinity`)
CLIProxy is responsible for mapping a single model ID to a pool of available credentials for a specific provider. 

The active strategy in `~/.cliproxy/config.yaml` is:
```yaml
routing:
  strategy: fill-first
  session-affinity: true
  session-affinity-ttl: 24h
```

- **`fill-first`**: Instead of load-balancing (round-robin), CLIProxy routes 100% of traffic to the **highest priority** credential until it exhausts its quota or hits a rate limit (429). Once it cools down, CLIProxy deterministically falls over to the next credential in the pool.
- **Priority Tiering**: Credentials can be assigned priority (e.g., `"priority": "100"`). For example, Claude models are configured to drain the native `claude` API key first. If it exhausts, it falls back to the `antigravity` Claude credentials (priority `0`), providing a seamless, same-model safety net.
- **`session-affinity`**: CLIProxy binds a specific conversation (identified by `metadata.user_id`, `X-Session-ID`, etc.) to the credential it started on for up to 24 hours. This maximizes **prompt caching** (context locality) because the same upstream cache handles the entire conversation thread, drastically reducing input token costs.

### LiteLLM: Model-Level Fallback
LiteLLM handles failovers when an entire provider pool in CLIProxy goes down or if the model doesn't exist.
- It uses `litellm_settings.fallbacks` to chain models.
- **Cross-provider tiering**: To fail over to a different provider for the *same* underlying model family (e.g., Antigravity Gemini → Gemini CLI), CLIProxy exposes special aliases (like `gemini-3-flash-via-gcli`). LiteLLM tries `gemini-3-flash` (Antigravity), and if it fails, it falls back to `gemini-3-flash-via-gcli` (Gemini CLI provider), before finally degrading to Claude or GPT.

## 2. Scaling (Adding More Accounts/Providers)

The architecture scales horizontally simply by adding more OAuth credentials to the `~/.cli-proxy-api/` directory.

- **Adding more native API keys or Antigravity accounts**: Drop a new JSON file into the folder. CLIProxy automatically adds it to the provider pool. If you assign it a priority, it slots exactly where you want it in the `fill-first` drain order. If priorities match, it sorts deterministically by credential ID.
- **Multi-Project Gemini Accounts**: If a single Gemini CLI file contains multiple GCP project IDs (or you have multiple files), CLIProxy automatically creates "virtual parent" credential groups. It will drain one project, then seamlessly fall over to the next project, creating massive headroom without any config changes.
- **Adding New Providers**: Adding a provider like OpenRouter simply requires defining it in `litellm-config.yaml` and appending it to the end of the `fallbacks` arrays.

## 3. Potential Improvements

### Within the Current Stack
- **`quota-aware` Strategy**: If latency is highly sensitive, CLIProxy could be switched from `fill-first` to `quota-aware`. This relies on live rate-limit headers to switch credentials *before* they hit a hard 429, preventing the momentary lag of a failed request. However, this trades away some prompt caching efficiency.
- **TTL Tuning**: If upstream providers aggressively evict caches (Anthropic evicts at 5 mins), a `24h` session affinity TTL might unnecessarily bind a session to an exhausted key if the user walks away for an hour. Lowering the TTL to `1h` might balance cache locality with load distribution better.

### Patching the Stack
- **Native Cross-Provider Aliasing in CLIProxy**: Currently, Tier-1 to Tier-2 failover (Antigravity → Gemini CLI) requires LiteLLM to maintain parallel model entries (`-via-gcli`). Patching CLIProxy to allow `oauth-model-alias` to pool across different underlying providers would simplify `litellm-config.yaml` massively. 

### Middleware Adjustments
- **Capability Polyfilling**: Adding a middleware layer in `main.py` that can strip or polyfill unsupported parameters across families.

## 4. Limitations and Quirks

- **Cross-Family Tool Call Failures**: 
  When LiteLLM falls back across model families (e.g., Gemini → Claude or Claude → GPT) mid-conversation, it often causes a `400 BadRequest`. This happens because the conversation history contains a `function_call` structured for Gemini, but the fallback model expects a different schema or tool execution format. 
- **Prompt Caching on Failover**: 
  While `fill-first` is highly token-efficient, if a credential hits a 429 *mid-conversation*, the session is forced onto the next credential. That next credential has a cold cache, meaning the user will pay full input token costs for that specific turn.
- **Provider-Specific Capabilities**: 
  Falling back across families breaks proprietary features. If a user is relying on Claude's "Computer Use" or Gemini's "Google Search Grounding", falling back to GPT-5 will strip those capabilities, likely breaking the agent's workflow.
- **Session Affinity and Caching**:
  Affinity groups the requests, but the actual token savings depend entirely on the upstream provider's cache eviction policy. If you pause a Claude session for 6 minutes, Anthropic flushes the cache. CLIProxy will still route you to the same credential, but you will pay for a cold start regardless.