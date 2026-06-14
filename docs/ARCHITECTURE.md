# Architecture Decision Record (ADR) — MCP Control Plane Hosting

This document defines and locks down the Model Context Protocol (MCP) hosting, transport, and authentication architecture for the AI Gateway. 

---

## 1. Context & Background

The Model Context Protocol (MCP) allows large language models (LLMs) to interact with external tools, APIs, and data sources. Since the AI Gateway acts as a centralized interface for LLMs across various platforms (OpenAI, Anthropic, Gemini, etc.), it must establish a standard, unified way to host, register, and authorize MCP servers.

Scaffolding was already established for MCP containerized search services (`mcp-brave`, `mcp-tavily`, etc.) in `docker-compose.yml`, but without a formal control-plane architecture, individual servers risked being fragmented across layer boundaries.

---

## 2. Decision: LiteLLM as the MCP Control Plane

We formally establish **LiteLLM (v1.82+) as the sole MCP control plane and routing coordinator**. 

```
┌────────────────────────────────────────────────────────┐
│                     Client (e.g. Cursor)               │
└───────────────────────────┬────────────────────────────┘
                            │ (OpenAI Chat API)
                            ▼
┌────────────────────────────────────────────────────────┐
│                   Gateway Engine Proxy                     │
└───────────────────────────┬────────────────────────────┘
                            │ (Pass-through with metadata)
                            ▼
┌────────────────────────────────────────────────────────┐
│                        LiteLLM                         │
│             (Configures and calls MCP Tools)           │
└────┬──────────────────────┬──────────────────────┬─────┘
     │ (stdio pipe)         │ (HTTP/SSE)           │ (HTTP/SSE)
     ▼                      ▼                      ▼
┌──────────────┐      ┌──────────────┐      ┌──────────────┐
│  Git Server  │      │ Brave Server │      │ Github Server│
└──────────────┘      └──────────────┘      └──────────────┘
```

### Architectural Mandates

1. **LiteLLM Config-File Registration:**
   All MCP servers must be explicitly declared and registered in `/etc/litellm/config.yaml` (or local `litellm-config.yaml`) under the `mcp_servers:` configuration block.
   
2. **Translation Layer Isolation:**
   **No MCP routing, dispatching, or tool-execution logic should ever reside in `main.py`**. The gateway-engine's sole responsibility is format normalization and credential mapping. Tool calls and executions are completely standard downstream LiteLLM behaviors.

3. **Standard Tool Schema Downstream:**
   When a client requests completions, LiteLLM exposes registered MCP tools as standard OpenAI-compatible tool definitions. The gateway-engine proxy simply passes these definitions through to the client.

---

## 3. Transport Strategy

MCP supports two primary transport methods: **stdio pipes** and **HTTP/SSE (Server-Sent Events)**.

### A. stdio Transport (Default & Preferred for Local/Internal Tools)
- **Mechanism:** LiteLLM launches the MCP server binary/command as a child sub-process and communicates with it over `stdin` and `stdout`.
- **Usage:** Used for internal system-level tasks (e.g., git control, filesystem access, local execution).
- **Pros:** Zero-network overhead, automatically inherits LiteLLM's local filesystem context, lifecycle is tied directly to the container/process.

### B. HTTP/SSE Transport (Preferred for Remote/Multi-Tenant/Containerized Tools)
- **Mechanism:** The MCP server runs as a separate container or standalone service. It exposes an HTTP endpoint that sends tools metadata and streams results back via SSE.
- **Usage:** Used for third-party search APIs (Brave, Tavily) or decoupled cloud tools (GitHub integration).
- **Bridge Tool (Supergateway):** If a local stdio MCP server needs to be exposed to multiple external clients or container networks, we bridge it to HTTP/SSE using `supergateway`.

---

## 4. Authentication & Authorization Model

To ensure security across various tool types, we categorize authentication into three distinct tiers:

| Server Category | Key Examples | Transport | Auth Model | Key/Token Storage |
| :--- | :--- | :--- | :--- | :--- |
| **System Tools** | Filesystem, Git, Sequential Thinking | `stdio` | None (Process-level trust) | Implicitly inherits container-level privileges |
| **Global APIs** | Brave, Tavily, Exa, Serper | `HTTP/SSE` | API Key (Static header) | Env variables inside `.env` (`BRAVE_API_KEY`, etc.) |
| **User/Tenant Credentials** | GitHub, PostgreSQL Custom Server | `HTTP/SSE` or `stdio` | Dynamic OAuth or User Tokens | Stored in LiteLLM DB / Vault, passed via bearer headers |

---

## 5. Implementation Specification

### A. Example `litellm-config.yaml` Integration
To register MCP servers in LiteLLM, we append them to the main configuration file as follows:

```yaml
mcp_servers:
  # Filesystem tool (stdio transport)
  mcp-filesystem:
    command: "npx"
    args: ["-y", "@modelcontextprotocol/server-filesystem", "/home/dev/workspace"]

  # Git operations (stdio transport)
  mcp-git:
    command: "npx"
    args: ["-y", "@modelcontextprotocol/server-git", "--repository", "/home/dev/repos/ai-gateway"]

  # Web Search via Brave (HTTP/SSE transport)
  mcp-brave:
    command: "npx"
    args: ["-y", "@modelcontextprotocol/server-brave"]
    env:
      BRAVE_API_KEY: "os.environ/BRAVE_API_KEY"
```

---

## 6. Consequences & Future Roadmap

- **Simplicity:** Client tools do not need custom MCP clients. They talk standard OpenAI tool-calling to the AI Gateway, and LiteLLM does the translation automatically.
- **Security:** Tight control of filesystem access within the Docker container bounds. Unprivileged access to external tools is protected by environment-level API key variables.
- **Extensibility:** Adding a new tool is as simple as registering a new item under `mcp_servers:` in the `litellm-config.yaml` file.
