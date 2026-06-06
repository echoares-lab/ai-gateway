-- Pre-migrated LiteLLM schema for mock/CI/dev stacks (regenerate: scripts/generate-litellm-mock-seed.sh)
-- LiteLLM image: ghcr.io/berriai/litellm:v1.87.1
\connect litellm
--
-- PostgreSQL database dump
--

\restrict k2utT3RLep2AD57pla1t0aR4E7LUFgQyWnpZ6hatE9f7ajOMPtprIPdMdK0Ch1A

-- Dumped from database version 17.10 (Debian 17.10-1.pgdg13+1)
-- Dumped by pg_dump version 17.10 (Debian 17.10-1.pgdg13+1)

SET statement_timeout = 0;
SET lock_timeout = 0;
SET idle_in_transaction_session_timeout = 0;
SET transaction_timeout = 0;
SET client_encoding = 'UTF8';
SET standard_conforming_strings = on;
SELECT pg_catalog.set_config('search_path', '', false);
SET check_function_bodies = false;
SET xmloption = content;
SET client_min_messages = warning;
SET row_security = off;

--
-- Name: JobStatus; Type: TYPE; Schema: public; Owner: -
--

CREATE TYPE public."JobStatus" AS ENUM (
    'ACTIVE',
    'INACTIVE'
);


--
-- Name: set_credential_inventory_updated_at(); Type: FUNCTION; Schema: public; Owner: -
--

CREATE FUNCTION public.set_credential_inventory_updated_at() RETURNS trigger
    LANGUAGE plpgsql
    AS $$
BEGIN
    NEW.updated_at = now();
    RETURN NEW;
END;
$$;


SET default_tablespace = '';

SET default_table_access_method = heap;

--
-- Name: LiteLLM_SpendLogs; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public."LiteLLM_SpendLogs" (
    request_id text NOT NULL,
    call_type text NOT NULL,
    api_key text DEFAULT ''::text NOT NULL,
    spend double precision DEFAULT 0.0 NOT NULL,
    total_tokens integer DEFAULT 0 NOT NULL,
    prompt_tokens integer DEFAULT 0 NOT NULL,
    completion_tokens integer DEFAULT 0 NOT NULL,
    "startTime" timestamp(3) without time zone NOT NULL,
    "endTime" timestamp(3) without time zone NOT NULL,
    "completionStartTime" timestamp(3) without time zone,
    model text DEFAULT ''::text NOT NULL,
    model_id text DEFAULT ''::text,
    model_group text DEFAULT ''::text,
    custom_llm_provider text DEFAULT ''::text,
    api_base text DEFAULT ''::text,
    "user" text DEFAULT ''::text,
    metadata jsonb DEFAULT '{}'::jsonb,
    cache_hit text DEFAULT ''::text,
    cache_key text DEFAULT ''::text,
    request_tags jsonb DEFAULT '[]'::jsonb,
    team_id text,
    end_user text,
    requester_ip_address text,
    messages jsonb DEFAULT '{}'::jsonb,
    response jsonb DEFAULT '{}'::jsonb,
    proxy_server_request jsonb DEFAULT '{}'::jsonb,
    session_id text,
    status text,
    mcp_namespaced_tool_name text,
    organization_id text,
    agent_id text,
    request_duration_ms integer
);


--
-- Name: DailyTagSpend; Type: VIEW; Schema: public; Owner: -
--

CREATE VIEW public."DailyTagSpend" AS
 SELECT jsonb_array_elements_text(request_tags) AS individual_request_tag,
    date("startTime") AS spend_date,
    count(*) AS log_count,
    sum(spend) AS total_spend
   FROM public."LiteLLM_SpendLogs" s
  GROUP BY (jsonb_array_elements_text(request_tags)), (date("startTime"));


--
-- Name: LiteLLM_VerificationToken; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public."LiteLLM_VerificationToken" (
    token text NOT NULL,
    key_name text,
    key_alias text,
    soft_budget_cooldown boolean DEFAULT false NOT NULL,
    spend double precision DEFAULT 0.0 NOT NULL,
    expires timestamp(3) without time zone,
    models text[],
    aliases jsonb DEFAULT '{}'::jsonb NOT NULL,
    config jsonb DEFAULT '{}'::jsonb NOT NULL,
    user_id text,
    team_id text,
    permissions jsonb DEFAULT '{}'::jsonb NOT NULL,
    max_parallel_requests integer,
    metadata jsonb DEFAULT '{}'::jsonb NOT NULL,
    blocked boolean,
    tpm_limit bigint,
    rpm_limit bigint,
    max_budget double precision,
    budget_duration text,
    budget_reset_at timestamp(3) without time zone,
    allowed_cache_controls text[] DEFAULT ARRAY[]::text[],
    model_spend jsonb DEFAULT '{}'::jsonb NOT NULL,
    model_max_budget jsonb DEFAULT '{}'::jsonb NOT NULL,
    budget_id text,
    organization_id text,
    created_at timestamp(3) without time zone DEFAULT CURRENT_TIMESTAMP,
    created_by text,
    updated_at timestamp(3) without time zone DEFAULT CURRENT_TIMESTAMP,
    updated_by text,
    allowed_routes text[] DEFAULT ARRAY[]::text[],
    object_permission_id text,
    auto_rotate boolean DEFAULT false,
    key_rotation_at timestamp(3) without time zone,
    last_rotation_at timestamp(3) without time zone,
    rotation_count integer DEFAULT 0,
    rotation_interval text,
    project_id text,
    router_settings jsonb DEFAULT '{}'::jsonb,
    policies text[] DEFAULT ARRAY[]::text[],
    access_group_ids text[] DEFAULT ARRAY[]::text[],
    last_active timestamp(3) without time zone,
    agent_id text,
    budget_limits jsonb
);


--
-- Name: Last30dKeysBySpend; Type: VIEW; Schema: public; Owner: -
--

CREATE VIEW public."Last30dKeysBySpend" AS
 SELECT l.api_key,
    v.key_alias,
    v.key_name,
    sum(l.spend) AS total_spend
   FROM (public."LiteLLM_SpendLogs" l
     LEFT JOIN public."LiteLLM_VerificationToken" v ON ((l.api_key = v.token)))
  WHERE (l."startTime" >= (CURRENT_DATE - '30 days'::interval))
  GROUP BY l.api_key, v.key_alias, v.key_name
  ORDER BY (sum(l.spend)) DESC;


--
-- Name: Last30dModelsBySpend; Type: VIEW; Schema: public; Owner: -
--

CREATE VIEW public."Last30dModelsBySpend" AS
 SELECT model,
    sum(spend) AS total_spend
   FROM public."LiteLLM_SpendLogs"
  WHERE (("startTime" >= (CURRENT_DATE - '30 days'::interval)) AND (model <> ''::text))
  GROUP BY model
  ORDER BY (sum(spend)) DESC;


--
-- Name: Last30dTopEndUsersSpend; Type: VIEW; Schema: public; Owner: -
--

CREATE VIEW public."Last30dTopEndUsersSpend" AS
 SELECT end_user,
    count(*) AS total_events,
    sum(spend) AS total_spend
   FROM public."LiteLLM_SpendLogs"
  WHERE ((end_user <> ''::text) AND (end_user <> USER) AND ("startTime" >= (CURRENT_DATE - '30 days'::interval)))
  GROUP BY end_user
  ORDER BY (sum(spend)) DESC
 LIMIT 100;


--
-- Name: LiteLLM_AccessGroupTable; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public."LiteLLM_AccessGroupTable" (
    access_group_id text NOT NULL,
    access_group_name text NOT NULL,
    description text,
    access_mcp_server_ids text[] DEFAULT ARRAY[]::text[],
    access_agent_ids text[] DEFAULT ARRAY[]::text[],
    assigned_team_ids text[] DEFAULT ARRAY[]::text[],
    assigned_key_ids text[] DEFAULT ARRAY[]::text[],
    created_at timestamp(3) without time zone DEFAULT CURRENT_TIMESTAMP NOT NULL,
    created_by text,
    updated_at timestamp(3) without time zone DEFAULT CURRENT_TIMESTAMP NOT NULL,
    updated_by text,
    access_model_names text[] DEFAULT ARRAY[]::text[]
);


--
-- Name: LiteLLM_AdaptiveRouterSession; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public."LiteLLM_AdaptiveRouterSession" (
    session_id text NOT NULL,
    router_name text NOT NULL,
    model_name text NOT NULL,
    classified_type text NOT NULL,
    misalignment_count integer DEFAULT 0 NOT NULL,
    stagnation_count integer DEFAULT 0 NOT NULL,
    disengagement_count integer DEFAULT 0 NOT NULL,
    satisfaction_count integer DEFAULT 0 NOT NULL,
    failure_count integer DEFAULT 0 NOT NULL,
    loop_count integer DEFAULT 0 NOT NULL,
    exhaustion_count integer DEFAULT 0 NOT NULL,
    last_user_content text,
    last_assistant_content text,
    tool_call_history jsonb DEFAULT '[]'::jsonb NOT NULL,
    pending_tool_calls jsonb DEFAULT '{}'::jsonb NOT NULL,
    turn_count integer DEFAULT 0 NOT NULL,
    last_processed_turn integer DEFAULT '-1'::integer NOT NULL,
    clean_credit_awarded boolean DEFAULT false NOT NULL,
    terminal_status integer,
    last_activity_at timestamp(3) without time zone DEFAULT CURRENT_TIMESTAMP NOT NULL
);


--
-- Name: LiteLLM_AdaptiveRouterState; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public."LiteLLM_AdaptiveRouterState" (
    router_name text NOT NULL,
    request_type text NOT NULL,
    model_name text NOT NULL,
    alpha double precision NOT NULL,
    beta double precision NOT NULL,
    total_samples integer DEFAULT 0 NOT NULL,
    last_updated_at timestamp(3) without time zone DEFAULT CURRENT_TIMESTAMP NOT NULL
);


--
-- Name: LiteLLM_AgentsTable; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public."LiteLLM_AgentsTable" (
    agent_id text NOT NULL,
    agent_name text NOT NULL,
    litellm_params jsonb,
    agent_card_params jsonb NOT NULL,
    created_at timestamp(3) without time zone DEFAULT CURRENT_TIMESTAMP NOT NULL,
    created_by text NOT NULL,
    updated_at timestamp(3) without time zone DEFAULT CURRENT_TIMESTAMP NOT NULL,
    updated_by text NOT NULL,
    agent_access_groups text[] DEFAULT ARRAY[]::text[],
    object_permission_id text,
    spend double precision DEFAULT 0.0 NOT NULL,
    static_headers jsonb DEFAULT '{}'::jsonb,
    extra_headers text[] DEFAULT ARRAY[]::text[],
    tpm_limit integer,
    rpm_limit integer,
    session_tpm_limit integer,
    session_rpm_limit integer
);


--
-- Name: LiteLLM_AuditLog; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public."LiteLLM_AuditLog" (
    id text NOT NULL,
    updated_at timestamp(3) without time zone DEFAULT CURRENT_TIMESTAMP NOT NULL,
    changed_by text DEFAULT ''::text NOT NULL,
    changed_by_api_key text DEFAULT ''::text NOT NULL,
    action text NOT NULL,
    table_name text NOT NULL,
    object_id text NOT NULL,
    before_value jsonb,
    updated_values jsonb
);


--
-- Name: LiteLLM_BudgetTable; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public."LiteLLM_BudgetTable" (
    budget_id text NOT NULL,
    max_budget double precision,
    soft_budget double precision,
    max_parallel_requests integer,
    tpm_limit bigint,
    rpm_limit bigint,
    model_max_budget jsonb,
    budget_duration text,
    budget_reset_at timestamp(3) without time zone,
    created_at timestamp(3) without time zone DEFAULT CURRENT_TIMESTAMP NOT NULL,
    created_by text NOT NULL,
    updated_at timestamp(3) without time zone DEFAULT CURRENT_TIMESTAMP NOT NULL,
    updated_by text NOT NULL,
    allowed_models text[] DEFAULT ARRAY[]::text[]
);


--
-- Name: LiteLLM_CacheConfig; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public."LiteLLM_CacheConfig" (
    id text DEFAULT 'cache_config'::text NOT NULL,
    cache_settings jsonb NOT NULL,
    created_at timestamp(3) without time zone DEFAULT CURRENT_TIMESTAMP NOT NULL,
    updated_at timestamp(3) without time zone NOT NULL
);


--
-- Name: LiteLLM_ClaudeCodePluginTable; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public."LiteLLM_ClaudeCodePluginTable" (
    id text NOT NULL,
    name text NOT NULL,
    version text,
    description text,
    manifest_json text,
    files_json text DEFAULT '{}'::text,
    enabled boolean DEFAULT true NOT NULL,
    created_at timestamp(3) without time zone DEFAULT CURRENT_TIMESTAMP,
    updated_at timestamp(3) without time zone DEFAULT CURRENT_TIMESTAMP,
    created_by text
);


--
-- Name: LiteLLM_Config; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public."LiteLLM_Config" (
    param_name text NOT NULL,
    param_value jsonb
);


--
-- Name: LiteLLM_ConfigOverrides; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public."LiteLLM_ConfigOverrides" (
    config_type text NOT NULL,
    config_value jsonb NOT NULL,
    created_at timestamp(3) without time zone DEFAULT CURRENT_TIMESTAMP NOT NULL,
    updated_at timestamp(3) without time zone NOT NULL
);


--
-- Name: LiteLLM_CredentialsTable; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public."LiteLLM_CredentialsTable" (
    credential_id text NOT NULL,
    credential_name text NOT NULL,
    credential_values jsonb NOT NULL,
    credential_info jsonb,
    created_at timestamp(3) without time zone DEFAULT CURRENT_TIMESTAMP NOT NULL,
    created_by text NOT NULL,
    updated_at timestamp(3) without time zone DEFAULT CURRENT_TIMESTAMP NOT NULL,
    updated_by text NOT NULL
);


--
-- Name: LiteLLM_CronJob; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public."LiteLLM_CronJob" (
    cronjob_id text NOT NULL,
    pod_id text NOT NULL,
    status public."JobStatus" DEFAULT 'INACTIVE'::public."JobStatus" NOT NULL,
    last_updated timestamp(3) without time zone DEFAULT CURRENT_TIMESTAMP NOT NULL,
    ttl timestamp(3) without time zone NOT NULL
);


--
-- Name: LiteLLM_DailyAgentSpend; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public."LiteLLM_DailyAgentSpend" (
    id text NOT NULL,
    agent_id text,
    date text NOT NULL,
    api_key text NOT NULL,
    model text,
    model_group text,
    custom_llm_provider text,
    mcp_namespaced_tool_name text,
    prompt_tokens bigint DEFAULT 0 NOT NULL,
    completion_tokens bigint DEFAULT 0 NOT NULL,
    cache_read_input_tokens bigint DEFAULT 0 NOT NULL,
    cache_creation_input_tokens bigint DEFAULT 0 NOT NULL,
    spend double precision DEFAULT 0.0 NOT NULL,
    api_requests bigint DEFAULT 0 NOT NULL,
    successful_requests bigint DEFAULT 0 NOT NULL,
    failed_requests bigint DEFAULT 0 NOT NULL,
    created_at timestamp(3) without time zone DEFAULT CURRENT_TIMESTAMP NOT NULL,
    updated_at timestamp(3) without time zone NOT NULL,
    endpoint text
);


--
-- Name: LiteLLM_DailyEndUserSpend; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public."LiteLLM_DailyEndUserSpend" (
    id text NOT NULL,
    end_user_id text,
    date text NOT NULL,
    api_key text NOT NULL,
    model text,
    model_group text,
    custom_llm_provider text,
    mcp_namespaced_tool_name text,
    prompt_tokens bigint DEFAULT 0 NOT NULL,
    completion_tokens bigint DEFAULT 0 NOT NULL,
    cache_read_input_tokens bigint DEFAULT 0 NOT NULL,
    cache_creation_input_tokens bigint DEFAULT 0 NOT NULL,
    spend double precision DEFAULT 0.0 NOT NULL,
    api_requests bigint DEFAULT 0 NOT NULL,
    successful_requests bigint DEFAULT 0 NOT NULL,
    failed_requests bigint DEFAULT 0 NOT NULL,
    created_at timestamp(3) without time zone DEFAULT CURRENT_TIMESTAMP NOT NULL,
    updated_at timestamp(3) without time zone NOT NULL,
    endpoint text
);


--
-- Name: LiteLLM_DailyGuardrailMetrics; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public."LiteLLM_DailyGuardrailMetrics" (
    guardrail_id text NOT NULL,
    date text NOT NULL,
    requests_evaluated bigint DEFAULT 0 NOT NULL,
    passed_count bigint DEFAULT 0 NOT NULL,
    blocked_count bigint DEFAULT 0 NOT NULL,
    flagged_count bigint DEFAULT 0 NOT NULL,
    avg_score double precision,
    avg_latency_ms double precision,
    created_at timestamp(3) without time zone DEFAULT CURRENT_TIMESTAMP NOT NULL,
    updated_at timestamp(3) without time zone NOT NULL
);


--
-- Name: LiteLLM_DailyOrganizationSpend; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public."LiteLLM_DailyOrganizationSpend" (
    id text NOT NULL,
    organization_id text,
    date text NOT NULL,
    api_key text NOT NULL,
    model text,
    model_group text,
    custom_llm_provider text,
    mcp_namespaced_tool_name text,
    prompt_tokens bigint DEFAULT 0 NOT NULL,
    completion_tokens bigint DEFAULT 0 NOT NULL,
    cache_read_input_tokens bigint DEFAULT 0 NOT NULL,
    cache_creation_input_tokens bigint DEFAULT 0 NOT NULL,
    spend double precision DEFAULT 0.0 NOT NULL,
    api_requests bigint DEFAULT 0 NOT NULL,
    successful_requests bigint DEFAULT 0 NOT NULL,
    failed_requests bigint DEFAULT 0 NOT NULL,
    created_at timestamp(3) without time zone DEFAULT CURRENT_TIMESTAMP NOT NULL,
    updated_at timestamp(3) without time zone NOT NULL,
    endpoint text
);


--
-- Name: LiteLLM_DailyPolicyMetrics; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public."LiteLLM_DailyPolicyMetrics" (
    policy_id text NOT NULL,
    date text NOT NULL,
    requests_evaluated bigint DEFAULT 0 NOT NULL,
    passed_count bigint DEFAULT 0 NOT NULL,
    blocked_count bigint DEFAULT 0 NOT NULL,
    flagged_count bigint DEFAULT 0 NOT NULL,
    avg_score double precision,
    avg_latency_ms double precision,
    created_at timestamp(3) without time zone DEFAULT CURRENT_TIMESTAMP NOT NULL,
    updated_at timestamp(3) without time zone NOT NULL
);


--
-- Name: LiteLLM_DailyTagSpend; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public."LiteLLM_DailyTagSpend" (
    id text NOT NULL,
    tag text,
    date text NOT NULL,
    api_key text NOT NULL,
    model text,
    model_group text,
    custom_llm_provider text,
    prompt_tokens bigint DEFAULT 0 NOT NULL,
    completion_tokens bigint DEFAULT 0 NOT NULL,
    cache_read_input_tokens bigint DEFAULT 0 NOT NULL,
    cache_creation_input_tokens bigint DEFAULT 0 NOT NULL,
    spend double precision DEFAULT 0.0 NOT NULL,
    api_requests bigint DEFAULT 0 NOT NULL,
    successful_requests bigint DEFAULT 0 NOT NULL,
    failed_requests bigint DEFAULT 0 NOT NULL,
    created_at timestamp(3) without time zone DEFAULT CURRENT_TIMESTAMP NOT NULL,
    updated_at timestamp(3) without time zone NOT NULL,
    mcp_namespaced_tool_name text,
    request_id text,
    endpoint text
);


--
-- Name: LiteLLM_DailyTeamSpend; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public."LiteLLM_DailyTeamSpend" (
    id text NOT NULL,
    team_id text,
    date text NOT NULL,
    api_key text NOT NULL,
    model text,
    model_group text,
    custom_llm_provider text,
    prompt_tokens bigint DEFAULT 0 NOT NULL,
    completion_tokens bigint DEFAULT 0 NOT NULL,
    spend double precision DEFAULT 0.0 NOT NULL,
    api_requests bigint DEFAULT 0 NOT NULL,
    successful_requests bigint DEFAULT 0 NOT NULL,
    failed_requests bigint DEFAULT 0 NOT NULL,
    created_at timestamp(3) without time zone DEFAULT CURRENT_TIMESTAMP NOT NULL,
    updated_at timestamp(3) without time zone NOT NULL,
    cache_creation_input_tokens bigint DEFAULT 0 NOT NULL,
    cache_read_input_tokens bigint DEFAULT 0 NOT NULL,
    mcp_namespaced_tool_name text,
    endpoint text
);


--
-- Name: LiteLLM_DailyUserSpend; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public."LiteLLM_DailyUserSpend" (
    id text NOT NULL,
    user_id text,
    date text NOT NULL,
    api_key text NOT NULL,
    model text,
    model_group text,
    custom_llm_provider text,
    prompt_tokens bigint DEFAULT 0 NOT NULL,
    completion_tokens bigint DEFAULT 0 NOT NULL,
    spend double precision DEFAULT 0.0 NOT NULL,
    created_at timestamp(3) without time zone DEFAULT CURRENT_TIMESTAMP NOT NULL,
    updated_at timestamp(3) without time zone NOT NULL,
    api_requests bigint DEFAULT 0 NOT NULL,
    failed_requests bigint DEFAULT 0 NOT NULL,
    successful_requests bigint DEFAULT 0 NOT NULL,
    cache_creation_input_tokens bigint DEFAULT 0 NOT NULL,
    cache_read_input_tokens bigint DEFAULT 0 NOT NULL,
    mcp_namespaced_tool_name text,
    endpoint text
);


--
-- Name: LiteLLM_DeletedTeamTable; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public."LiteLLM_DeletedTeamTable" (
    id text NOT NULL,
    team_id text NOT NULL,
    team_alias text,
    organization_id text,
    object_permission_id text,
    admins text[],
    members text[],
    members_with_roles jsonb DEFAULT '{}'::jsonb NOT NULL,
    metadata jsonb DEFAULT '{}'::jsonb NOT NULL,
    max_budget double precision,
    spend double precision DEFAULT 0.0 NOT NULL,
    models text[],
    max_parallel_requests integer,
    tpm_limit bigint,
    rpm_limit bigint,
    budget_duration text,
    budget_reset_at timestamp(3) without time zone,
    blocked boolean DEFAULT false NOT NULL,
    model_spend jsonb DEFAULT '{}'::jsonb NOT NULL,
    model_max_budget jsonb DEFAULT '{}'::jsonb NOT NULL,
    team_member_permissions text[] DEFAULT ARRAY[]::text[],
    model_id integer,
    created_at timestamp(3) without time zone,
    updated_at timestamp(3) without time zone,
    deleted_at timestamp(3) without time zone DEFAULT CURRENT_TIMESTAMP NOT NULL,
    deleted_by text,
    deleted_by_api_key text,
    litellm_changed_by text,
    router_settings jsonb DEFAULT '{}'::jsonb,
    policies text[] DEFAULT ARRAY[]::text[],
    allow_team_guardrail_config boolean DEFAULT false NOT NULL,
    soft_budget double precision,
    access_group_ids text[] DEFAULT ARRAY[]::text[]
);


--
-- Name: LiteLLM_DeletedVerificationToken; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public."LiteLLM_DeletedVerificationToken" (
    id text NOT NULL,
    token text NOT NULL,
    key_name text,
    key_alias text,
    soft_budget_cooldown boolean DEFAULT false NOT NULL,
    spend double precision DEFAULT 0.0 NOT NULL,
    expires timestamp(3) without time zone,
    models text[],
    aliases jsonb DEFAULT '{}'::jsonb NOT NULL,
    config jsonb DEFAULT '{}'::jsonb NOT NULL,
    user_id text,
    team_id text,
    permissions jsonb DEFAULT '{}'::jsonb NOT NULL,
    max_parallel_requests integer,
    metadata jsonb DEFAULT '{}'::jsonb NOT NULL,
    blocked boolean,
    tpm_limit bigint,
    rpm_limit bigint,
    max_budget double precision,
    budget_duration text,
    budget_reset_at timestamp(3) without time zone,
    allowed_cache_controls text[] DEFAULT ARRAY[]::text[],
    allowed_routes text[] DEFAULT ARRAY[]::text[],
    model_spend jsonb DEFAULT '{}'::jsonb NOT NULL,
    model_max_budget jsonb DEFAULT '{}'::jsonb NOT NULL,
    budget_id text,
    organization_id text,
    object_permission_id text,
    created_at timestamp(3) without time zone,
    created_by text,
    updated_at timestamp(3) without time zone,
    updated_by text,
    rotation_count integer DEFAULT 0,
    auto_rotate boolean DEFAULT false,
    rotation_interval text,
    last_rotation_at timestamp(3) without time zone,
    key_rotation_at timestamp(3) without time zone,
    deleted_at timestamp(3) without time zone DEFAULT CURRENT_TIMESTAMP NOT NULL,
    deleted_by text,
    deleted_by_api_key text,
    litellm_changed_by text,
    router_settings jsonb DEFAULT '{}'::jsonb,
    policies text[] DEFAULT ARRAY[]::text[],
    access_group_ids text[] DEFAULT ARRAY[]::text[],
    last_active timestamp(3) without time zone,
    project_id text,
    agent_id text
);


--
-- Name: LiteLLM_DeprecatedVerificationToken; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public."LiteLLM_DeprecatedVerificationToken" (
    id text NOT NULL,
    token text NOT NULL,
    active_token_id text NOT NULL,
    revoke_at timestamp(3) without time zone NOT NULL,
    created_at timestamp(3) without time zone DEFAULT CURRENT_TIMESTAMP NOT NULL
);


--
-- Name: LiteLLM_EndUserTable; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public."LiteLLM_EndUserTable" (
    user_id text NOT NULL,
    alias text,
    spend double precision DEFAULT 0.0 NOT NULL,
    allowed_model_region text,
    default_model text,
    budget_id text,
    blocked boolean DEFAULT false NOT NULL,
    object_permission_id text
);


--
-- Name: LiteLLM_ErrorLogs; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public."LiteLLM_ErrorLogs" (
    request_id text NOT NULL,
    "startTime" timestamp(3) without time zone NOT NULL,
    "endTime" timestamp(3) without time zone NOT NULL,
    api_base text DEFAULT ''::text NOT NULL,
    model_group text DEFAULT ''::text NOT NULL,
    litellm_model_name text DEFAULT ''::text NOT NULL,
    model_id text DEFAULT ''::text NOT NULL,
    request_kwargs jsonb DEFAULT '{}'::jsonb NOT NULL,
    exception_type text DEFAULT ''::text NOT NULL,
    exception_string text DEFAULT ''::text NOT NULL,
    status_code text DEFAULT ''::text NOT NULL
);


--
-- Name: LiteLLM_GuardrailsTable; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public."LiteLLM_GuardrailsTable" (
    guardrail_id text NOT NULL,
    guardrail_name text NOT NULL,
    litellm_params jsonb NOT NULL,
    guardrail_info jsonb,
    created_at timestamp(3) without time zone DEFAULT CURRENT_TIMESTAMP NOT NULL,
    updated_at timestamp(3) without time zone NOT NULL,
    team_id text,
    reviewed_at timestamp(3) without time zone,
    status text DEFAULT 'active'::text NOT NULL,
    submitted_at timestamp(3) without time zone
);


--
-- Name: LiteLLM_HealthCheckTable; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public."LiteLLM_HealthCheckTable" (
    health_check_id text NOT NULL,
    model_name text NOT NULL,
    model_id text,
    status text NOT NULL,
    healthy_count integer DEFAULT 0 NOT NULL,
    unhealthy_count integer DEFAULT 0 NOT NULL,
    error_message text,
    response_time_ms double precision,
    details jsonb,
    checked_by text,
    checked_at timestamp(3) without time zone DEFAULT CURRENT_TIMESTAMP NOT NULL,
    created_at timestamp(3) without time zone DEFAULT CURRENT_TIMESTAMP NOT NULL,
    updated_at timestamp(3) without time zone NOT NULL
);


--
-- Name: LiteLLM_InvitationLink; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public."LiteLLM_InvitationLink" (
    id text NOT NULL,
    user_id text NOT NULL,
    is_accepted boolean DEFAULT false NOT NULL,
    accepted_at timestamp(3) without time zone,
    expires_at timestamp(3) without time zone NOT NULL,
    created_at timestamp(3) without time zone NOT NULL,
    created_by text NOT NULL,
    updated_at timestamp(3) without time zone NOT NULL,
    updated_by text NOT NULL
);


--
-- Name: LiteLLM_JWTKeyMapping; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public."LiteLLM_JWTKeyMapping" (
    id text NOT NULL,
    jwt_claim_name text NOT NULL,
    jwt_claim_value text NOT NULL,
    token text NOT NULL,
    description text,
    is_active boolean DEFAULT true NOT NULL,
    created_at timestamp(3) without time zone DEFAULT CURRENT_TIMESTAMP NOT NULL,
    created_by text,
    updated_at timestamp(3) without time zone DEFAULT CURRENT_TIMESTAMP NOT NULL,
    updated_by text
);


--
-- Name: LiteLLM_MCPServerTable; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public."LiteLLM_MCPServerTable" (
    server_id text NOT NULL,
    server_name text,
    description text,
    url text,
    transport text DEFAULT 'sse'::text NOT NULL,
    auth_type text,
    created_at timestamp(3) without time zone DEFAULT CURRENT_TIMESTAMP,
    created_by text,
    updated_at timestamp(3) without time zone DEFAULT CURRENT_TIMESTAMP,
    updated_by text,
    status text DEFAULT 'unknown'::text,
    last_health_check timestamp(3) without time zone,
    health_check_error text,
    mcp_info jsonb DEFAULT '{}'::jsonb,
    args text[] DEFAULT ARRAY[]::text[],
    command text,
    env jsonb DEFAULT '{}'::jsonb,
    mcp_access_groups text[],
    alias text,
    allowed_tools text[] DEFAULT ARRAY[]::text[],
    extra_headers text[] DEFAULT ARRAY[]::text[],
    static_headers jsonb DEFAULT '{}'::jsonb,
    credentials jsonb DEFAULT '{}'::jsonb,
    authorization_url text,
    registration_url text,
    token_url text,
    allow_all_keys boolean DEFAULT false NOT NULL,
    available_on_public_internet boolean DEFAULT true NOT NULL,
    spec_path text,
    byok_api_key_help_url text,
    byok_description text[] DEFAULT ARRAY[]::text[],
    is_byok boolean DEFAULT false NOT NULL,
    tool_name_to_description jsonb DEFAULT '{}'::jsonb,
    tool_name_to_display_name jsonb DEFAULT '{}'::jsonb,
    approval_status text DEFAULT 'active'::text,
    review_notes text,
    reviewed_at timestamp(3) without time zone,
    submitted_at timestamp(3) without time zone,
    submitted_by text,
    source_url text,
    instructions text,
    delegate_auth_to_upstream boolean DEFAULT false NOT NULL
);


--
-- Name: LiteLLM_MCPToolsetTable; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public."LiteLLM_MCPToolsetTable" (
    toolset_id text NOT NULL,
    toolset_name text NOT NULL,
    description text,
    tools jsonb DEFAULT '[]'::jsonb NOT NULL,
    created_at timestamp(3) without time zone DEFAULT CURRENT_TIMESTAMP NOT NULL,
    created_by text,
    updated_at timestamp(3) without time zone DEFAULT CURRENT_TIMESTAMP NOT NULL,
    updated_by text
);


--
-- Name: LiteLLM_MCPUserCredentials; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public."LiteLLM_MCPUserCredentials" (
    id text NOT NULL,
    user_id text NOT NULL,
    server_id text NOT NULL,
    credential_b64 text NOT NULL,
    created_at timestamp(3) without time zone DEFAULT CURRENT_TIMESTAMP NOT NULL,
    updated_at timestamp(3) without time zone DEFAULT CURRENT_TIMESTAMP NOT NULL
);


--
-- Name: LiteLLM_ManagedFileTable; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public."LiteLLM_ManagedFileTable" (
    id text NOT NULL,
    unified_file_id text NOT NULL,
    file_object jsonb,
    model_mappings jsonb NOT NULL,
    created_at timestamp(3) without time zone DEFAULT CURRENT_TIMESTAMP NOT NULL,
    updated_at timestamp(3) without time zone NOT NULL,
    created_by text,
    flat_model_file_ids text[] DEFAULT ARRAY[]::text[],
    updated_by text,
    storage_backend text,
    storage_url text,
    team_id text
);


--
-- Name: LiteLLM_ManagedObjectTable; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public."LiteLLM_ManagedObjectTable" (
    id text NOT NULL,
    unified_object_id text NOT NULL,
    model_object_id text NOT NULL,
    file_object jsonb NOT NULL,
    file_purpose text NOT NULL,
    created_at timestamp(3) without time zone DEFAULT CURRENT_TIMESTAMP NOT NULL,
    created_by text,
    updated_at timestamp(3) without time zone NOT NULL,
    updated_by text,
    status text,
    batch_processed boolean DEFAULT false NOT NULL,
    team_id text
);


--
-- Name: LiteLLM_ManagedVectorStoreIndexTable; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public."LiteLLM_ManagedVectorStoreIndexTable" (
    id text NOT NULL,
    index_name text NOT NULL,
    litellm_params jsonb NOT NULL,
    index_info jsonb,
    created_at timestamp(3) without time zone DEFAULT CURRENT_TIMESTAMP NOT NULL,
    created_by text,
    updated_at timestamp(3) without time zone NOT NULL,
    updated_by text
);


--
-- Name: LiteLLM_ManagedVectorStoreTable; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public."LiteLLM_ManagedVectorStoreTable" (
    id text NOT NULL,
    unified_resource_id text NOT NULL,
    resource_object jsonb,
    model_mappings jsonb NOT NULL,
    flat_model_resource_ids text[] DEFAULT ARRAY[]::text[],
    storage_backend text,
    storage_url text,
    created_at timestamp(3) without time zone DEFAULT CURRENT_TIMESTAMP NOT NULL,
    created_by text,
    updated_at timestamp(3) without time zone NOT NULL,
    updated_by text,
    team_id text
);


--
-- Name: LiteLLM_ManagedVectorStoresTable; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public."LiteLLM_ManagedVectorStoresTable" (
    vector_store_id text NOT NULL,
    custom_llm_provider text NOT NULL,
    vector_store_name text,
    vector_store_description text,
    vector_store_metadata jsonb,
    created_at timestamp(3) without time zone DEFAULT CURRENT_TIMESTAMP NOT NULL,
    updated_at timestamp(3) without time zone NOT NULL,
    litellm_credential_name text,
    litellm_params jsonb,
    team_id text,
    user_id text
);


--
-- Name: LiteLLM_MemoryTable; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public."LiteLLM_MemoryTable" (
    memory_id text NOT NULL,
    key text NOT NULL,
    value text NOT NULL,
    metadata jsonb,
    user_id text,
    team_id text,
    created_at timestamp(3) without time zone DEFAULT CURRENT_TIMESTAMP NOT NULL,
    created_by text,
    updated_at timestamp(3) without time zone DEFAULT CURRENT_TIMESTAMP NOT NULL,
    updated_by text
);


--
-- Name: LiteLLM_ModelTable; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public."LiteLLM_ModelTable" (
    id integer NOT NULL,
    aliases jsonb,
    created_at timestamp(3) without time zone DEFAULT CURRENT_TIMESTAMP NOT NULL,
    created_by text NOT NULL,
    updated_at timestamp(3) without time zone DEFAULT CURRENT_TIMESTAMP NOT NULL,
    updated_by text NOT NULL
);


--
-- Name: LiteLLM_ModelTable_id_seq; Type: SEQUENCE; Schema: public; Owner: -
--

CREATE SEQUENCE public."LiteLLM_ModelTable_id_seq"
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


--
-- Name: LiteLLM_ModelTable_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: -
--

ALTER SEQUENCE public."LiteLLM_ModelTable_id_seq" OWNED BY public."LiteLLM_ModelTable".id;


--
-- Name: LiteLLM_ObjectPermissionTable; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public."LiteLLM_ObjectPermissionTable" (
    object_permission_id text NOT NULL,
    mcp_servers text[] DEFAULT ARRAY[]::text[],
    vector_stores text[] DEFAULT ARRAY[]::text[],
    mcp_access_groups text[] DEFAULT ARRAY[]::text[],
    mcp_tool_permissions jsonb,
    agents text[] DEFAULT ARRAY[]::text[],
    agent_access_groups text[] DEFAULT ARRAY[]::text[],
    blocked_tools text[] DEFAULT ARRAY[]::text[],
    models text[] DEFAULT ARRAY[]::text[],
    mcp_toolsets text[] DEFAULT ARRAY[]::text[],
    search_tools text[] DEFAULT ARRAY[]::text[]
);


--
-- Name: LiteLLM_OrganizationMembership; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public."LiteLLM_OrganizationMembership" (
    user_id text NOT NULL,
    organization_id text NOT NULL,
    user_role text,
    spend double precision DEFAULT 0.0,
    budget_id text,
    created_at timestamp(3) without time zone DEFAULT CURRENT_TIMESTAMP,
    updated_at timestamp(3) without time zone DEFAULT CURRENT_TIMESTAMP
);


--
-- Name: LiteLLM_OrganizationTable; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public."LiteLLM_OrganizationTable" (
    organization_id text NOT NULL,
    organization_alias text NOT NULL,
    budget_id text NOT NULL,
    metadata jsonb DEFAULT '{}'::jsonb NOT NULL,
    models text[],
    spend double precision DEFAULT 0.0 NOT NULL,
    model_spend jsonb DEFAULT '{}'::jsonb NOT NULL,
    created_at timestamp(3) without time zone DEFAULT CURRENT_TIMESTAMP NOT NULL,
    created_by text NOT NULL,
    updated_at timestamp(3) without time zone DEFAULT CURRENT_TIMESTAMP NOT NULL,
    updated_by text NOT NULL,
    object_permission_id text
);


--
-- Name: LiteLLM_PolicyAttachmentTable; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public."LiteLLM_PolicyAttachmentTable" (
    attachment_id text NOT NULL,
    policy_name text NOT NULL,
    scope text,
    teams text[] DEFAULT ARRAY[]::text[],
    keys text[] DEFAULT ARRAY[]::text[],
    models text[] DEFAULT ARRAY[]::text[],
    created_at timestamp(3) without time zone DEFAULT CURRENT_TIMESTAMP NOT NULL,
    created_by text,
    updated_at timestamp(3) without time zone DEFAULT CURRENT_TIMESTAMP NOT NULL,
    updated_by text,
    tags text[] DEFAULT ARRAY[]::text[]
);


--
-- Name: LiteLLM_PolicyTable; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public."LiteLLM_PolicyTable" (
    policy_id text NOT NULL,
    policy_name text NOT NULL,
    inherit text,
    description text,
    guardrails_add text[] DEFAULT ARRAY[]::text[],
    guardrails_remove text[] DEFAULT ARRAY[]::text[],
    condition jsonb DEFAULT '{}'::jsonb,
    created_at timestamp(3) without time zone DEFAULT CURRENT_TIMESTAMP NOT NULL,
    created_by text,
    updated_at timestamp(3) without time zone DEFAULT CURRENT_TIMESTAMP NOT NULL,
    updated_by text,
    pipeline jsonb,
    is_latest boolean DEFAULT true NOT NULL,
    parent_version_id text,
    production_at timestamp(3) without time zone,
    published_at timestamp(3) without time zone,
    version_number integer DEFAULT 1 NOT NULL,
    version_status text DEFAULT 'production'::text NOT NULL
);


--
-- Name: LiteLLM_ProjectTable; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public."LiteLLM_ProjectTable" (
    project_id text NOT NULL,
    project_alias text,
    team_id text,
    budget_id text,
    metadata jsonb DEFAULT '{}'::jsonb NOT NULL,
    models text[],
    spend double precision DEFAULT 0.0 NOT NULL,
    model_spend jsonb DEFAULT '{}'::jsonb NOT NULL,
    blocked boolean DEFAULT false NOT NULL,
    object_permission_id text,
    created_at timestamp(3) without time zone DEFAULT CURRENT_TIMESTAMP NOT NULL,
    created_by text NOT NULL,
    updated_at timestamp(3) without time zone DEFAULT CURRENT_TIMESTAMP NOT NULL,
    updated_by text NOT NULL,
    description text,
    model_rpm_limit jsonb DEFAULT '{}'::jsonb NOT NULL,
    model_tpm_limit jsonb DEFAULT '{}'::jsonb NOT NULL
);


--
-- Name: LiteLLM_PromptTable; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public."LiteLLM_PromptTable" (
    id text NOT NULL,
    prompt_id text NOT NULL,
    litellm_params jsonb NOT NULL,
    prompt_info jsonb,
    created_at timestamp(3) without time zone DEFAULT CURRENT_TIMESTAMP NOT NULL,
    updated_at timestamp(3) without time zone NOT NULL,
    version integer DEFAULT 1 NOT NULL,
    environment text DEFAULT 'development'::text NOT NULL,
    created_by text
);


--
-- Name: LiteLLM_ProxyModelTable; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public."LiteLLM_ProxyModelTable" (
    model_id text NOT NULL,
    model_name text NOT NULL,
    litellm_params jsonb NOT NULL,
    model_info jsonb,
    created_at timestamp(3) without time zone DEFAULT CURRENT_TIMESTAMP NOT NULL,
    created_by text NOT NULL,
    updated_at timestamp(3) without time zone DEFAULT CURRENT_TIMESTAMP NOT NULL,
    updated_by text NOT NULL,
    blocked boolean DEFAULT false NOT NULL
);


--
-- Name: LiteLLM_SSOConfig; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public."LiteLLM_SSOConfig" (
    id text DEFAULT 'sso_config'::text NOT NULL,
    sso_settings jsonb NOT NULL,
    created_at timestamp(3) without time zone DEFAULT CURRENT_TIMESTAMP NOT NULL,
    updated_at timestamp(3) without time zone NOT NULL
);


--
-- Name: LiteLLM_SearchToolsTable; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public."LiteLLM_SearchToolsTable" (
    search_tool_id text NOT NULL,
    search_tool_name text NOT NULL,
    litellm_params jsonb NOT NULL,
    search_tool_info jsonb,
    created_at timestamp(3) without time zone DEFAULT CURRENT_TIMESTAMP NOT NULL,
    updated_at timestamp(3) without time zone NOT NULL
);


--
-- Name: LiteLLM_SkillsTable; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public."LiteLLM_SkillsTable" (
    skill_id text NOT NULL,
    display_title text,
    description text,
    instructions text,
    source text DEFAULT 'custom'::text NOT NULL,
    latest_version text,
    file_content bytea,
    file_name text,
    file_type text,
    metadata jsonb DEFAULT '{}'::jsonb,
    created_at timestamp(3) without time zone DEFAULT CURRENT_TIMESTAMP NOT NULL,
    created_by text,
    updated_at timestamp(3) without time zone DEFAULT CURRENT_TIMESTAMP NOT NULL,
    updated_by text
);


--
-- Name: LiteLLM_SpendLogGuardrailIndex; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public."LiteLLM_SpendLogGuardrailIndex" (
    request_id text NOT NULL,
    guardrail_id text NOT NULL,
    policy_id text,
    start_time timestamp(3) without time zone NOT NULL
);


--
-- Name: LiteLLM_SpendLogToolIndex; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public."LiteLLM_SpendLogToolIndex" (
    request_id text NOT NULL,
    tool_name text NOT NULL,
    start_time timestamp(3) without time zone NOT NULL
);


--
-- Name: LiteLLM_TagTable; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public."LiteLLM_TagTable" (
    tag_name text NOT NULL,
    description text,
    models text[],
    model_info jsonb,
    spend double precision DEFAULT 0.0 NOT NULL,
    budget_id text,
    created_at timestamp(3) without time zone DEFAULT CURRENT_TIMESTAMP NOT NULL,
    created_by text,
    updated_at timestamp(3) without time zone DEFAULT CURRENT_TIMESTAMP NOT NULL
);


--
-- Name: LiteLLM_TeamMembership; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public."LiteLLM_TeamMembership" (
    user_id text NOT NULL,
    team_id text NOT NULL,
    spend double precision DEFAULT 0.0 NOT NULL,
    budget_id text,
    total_spend double precision DEFAULT 0.0 NOT NULL
);


--
-- Name: LiteLLM_TeamTable; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public."LiteLLM_TeamTable" (
    team_id text NOT NULL,
    team_alias text,
    organization_id text,
    admins text[],
    members text[],
    members_with_roles jsonb DEFAULT '{}'::jsonb NOT NULL,
    metadata jsonb DEFAULT '{}'::jsonb NOT NULL,
    max_budget double precision,
    spend double precision DEFAULT 0.0 NOT NULL,
    models text[],
    max_parallel_requests integer,
    tpm_limit bigint,
    rpm_limit bigint,
    budget_duration text,
    budget_reset_at timestamp(3) without time zone,
    blocked boolean DEFAULT false NOT NULL,
    created_at timestamp(3) without time zone DEFAULT CURRENT_TIMESTAMP NOT NULL,
    updated_at timestamp(3) without time zone DEFAULT CURRENT_TIMESTAMP NOT NULL,
    model_spend jsonb DEFAULT '{}'::jsonb NOT NULL,
    model_max_budget jsonb DEFAULT '{}'::jsonb NOT NULL,
    model_id integer,
    team_member_permissions text[] DEFAULT ARRAY[]::text[],
    object_permission_id text,
    router_settings jsonb DEFAULT '{}'::jsonb,
    policies text[] DEFAULT ARRAY[]::text[],
    allow_team_guardrail_config boolean DEFAULT false NOT NULL,
    soft_budget double precision,
    access_group_ids text[] DEFAULT ARRAY[]::text[],
    budget_limits jsonb,
    default_team_member_models text[] DEFAULT ARRAY[]::text[]
);


--
-- Name: LiteLLM_ToolTable; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public."LiteLLM_ToolTable" (
    tool_id text NOT NULL,
    tool_name text NOT NULL,
    origin text,
    input_policy text DEFAULT 'untrusted'::text NOT NULL,
    call_count integer DEFAULT 0 NOT NULL,
    assignments jsonb DEFAULT '{}'::jsonb,
    key_hash text,
    team_id text,
    key_alias text,
    created_at timestamp(3) without time zone DEFAULT CURRENT_TIMESTAMP NOT NULL,
    created_by text,
    updated_at timestamp(3) without time zone DEFAULT CURRENT_TIMESTAMP NOT NULL,
    updated_by text,
    output_policy text DEFAULT 'untrusted'::text NOT NULL,
    user_agent text,
    last_used_at timestamp(3) without time zone
);


--
-- Name: LiteLLM_UISettings; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public."LiteLLM_UISettings" (
    id text DEFAULT 'ui_settings'::text NOT NULL,
    ui_settings jsonb NOT NULL,
    created_at timestamp(3) without time zone DEFAULT CURRENT_TIMESTAMP NOT NULL,
    updated_at timestamp(3) without time zone NOT NULL
);


--
-- Name: LiteLLM_UserNotifications; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public."LiteLLM_UserNotifications" (
    request_id text NOT NULL,
    user_id text NOT NULL,
    models text[],
    justification text NOT NULL,
    status text NOT NULL
);


--
-- Name: LiteLLM_UserTable; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public."LiteLLM_UserTable" (
    user_id text NOT NULL,
    user_alias text,
    team_id text,
    sso_user_id text,
    organization_id text,
    password text,
    teams text[] DEFAULT ARRAY[]::text[],
    user_role text,
    max_budget double precision,
    spend double precision DEFAULT 0.0 NOT NULL,
    user_email text,
    models text[],
    metadata jsonb DEFAULT '{}'::jsonb NOT NULL,
    max_parallel_requests integer,
    tpm_limit bigint,
    rpm_limit bigint,
    budget_duration text,
    budget_reset_at timestamp(3) without time zone,
    allowed_cache_controls text[] DEFAULT ARRAY[]::text[],
    model_spend jsonb DEFAULT '{}'::jsonb NOT NULL,
    model_max_budget jsonb DEFAULT '{}'::jsonb NOT NULL,
    created_at timestamp(3) without time zone DEFAULT CURRENT_TIMESTAMP,
    updated_at timestamp(3) without time zone DEFAULT CURRENT_TIMESTAMP,
    object_permission_id text,
    policies text[] DEFAULT ARRAY[]::text[]
);


--
-- Name: LiteLLM_VerificationTokenView; Type: VIEW; Schema: public; Owner: -
--

CREATE VIEW public."LiteLLM_VerificationTokenView" AS
 SELECT v.token,
    v.key_name,
    v.key_alias,
    v.soft_budget_cooldown,
    v.spend,
    v.expires,
    v.models,
    v.aliases,
    v.config,
    v.user_id,
    v.team_id,
    v.permissions,
    v.max_parallel_requests,
    v.metadata,
    v.blocked,
    v.tpm_limit,
    v.rpm_limit,
    v.max_budget,
    v.budget_duration,
    v.budget_reset_at,
    v.allowed_cache_controls,
    v.model_spend,
    v.model_max_budget,
    v.budget_id,
    v.organization_id,
    v.created_at,
    v.created_by,
    v.updated_at,
    v.updated_by,
    v.allowed_routes,
    v.object_permission_id,
    v.auto_rotate,
    v.key_rotation_at,
    v.last_rotation_at,
    v.rotation_count,
    v.rotation_interval,
    v.project_id,
    v.router_settings,
    v.policies,
    v.access_group_ids,
    v.last_active,
    v.agent_id,
    t.spend AS team_spend,
    t.max_budget AS team_max_budget,
    t.tpm_limit AS team_tpm_limit,
    t.rpm_limit AS team_rpm_limit
   FROM (public."LiteLLM_VerificationToken" v
     LEFT JOIN public."LiteLLM_TeamTable" t ON ((v.team_id = t.team_id)));


--
-- Name: LiteLLM_WorkflowEvent; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public."LiteLLM_WorkflowEvent" (
    event_id text NOT NULL,
    run_id text NOT NULL,
    event_type text NOT NULL,
    step_name text NOT NULL,
    sequence_number integer NOT NULL,
    data jsonb,
    created_at timestamp(3) without time zone DEFAULT CURRENT_TIMESTAMP NOT NULL
);


--
-- Name: LiteLLM_WorkflowMessage; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public."LiteLLM_WorkflowMessage" (
    message_id text NOT NULL,
    run_id text NOT NULL,
    role text NOT NULL,
    content text NOT NULL,
    sequence_number integer NOT NULL,
    session_id text,
    created_at timestamp(3) without time zone DEFAULT CURRENT_TIMESTAMP NOT NULL
);


--
-- Name: LiteLLM_WorkflowRun; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public."LiteLLM_WorkflowRun" (
    run_id text NOT NULL,
    session_id text NOT NULL,
    workflow_type text NOT NULL,
    status text DEFAULT 'pending'::text NOT NULL,
    created_by text,
    created_at timestamp(3) without time zone DEFAULT CURRENT_TIMESTAMP NOT NULL,
    updated_at timestamp(3) without time zone NOT NULL,
    input jsonb,
    output jsonb,
    metadata jsonb
);


--
-- Name: MonthlyGlobalSpend; Type: VIEW; Schema: public; Owner: -
--

CREATE VIEW public."MonthlyGlobalSpend" AS
 SELECT date("startTime") AS date,
    sum(spend) AS spend
   FROM public."LiteLLM_SpendLogs"
  WHERE ("startTime" >= (CURRENT_DATE - '30 days'::interval))
  GROUP BY (date("startTime"));


--
-- Name: MonthlyGlobalSpendPerKey; Type: VIEW; Schema: public; Owner: -
--

CREATE VIEW public."MonthlyGlobalSpendPerKey" AS
 SELECT date("startTime") AS date,
    sum(spend) AS spend,
    api_key
   FROM public."LiteLLM_SpendLogs"
  WHERE ("startTime" >= (CURRENT_DATE - '30 days'::interval))
  GROUP BY (date("startTime")), api_key;


--
-- Name: MonthlyGlobalSpendPerUserPerKey; Type: VIEW; Schema: public; Owner: -
--

CREATE VIEW public."MonthlyGlobalSpendPerUserPerKey" AS
 SELECT date("startTime") AS date,
    sum(spend) AS spend,
    api_key,
    "user"
   FROM public."LiteLLM_SpendLogs"
  WHERE ("startTime" >= (CURRENT_DATE - '30 days'::interval))
  GROUP BY (date("startTime")), "user", api_key;


--
-- Name: _prisma_migrations; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public._prisma_migrations (
    id character varying(36) NOT NULL,
    checksum character varying(64) NOT NULL,
    finished_at timestamp with time zone,
    migration_name character varying(255) NOT NULL,
    logs text,
    rolled_back_at timestamp with time zone,
    started_at timestamp with time zone DEFAULT now() NOT NULL,
    applied_steps_count integer DEFAULT 0 NOT NULL
);


--
-- Name: credential_inventory; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.credential_inventory (
    credential_id text NOT NULL,
    provider text NOT NULL,
    label text NOT NULL,
    key_fingerprint text NOT NULL,
    status text DEFAULT 'HEALTHY'::text NOT NULL,
    cool_down_until timestamp with time zone,
    consecutive_failures integer DEFAULT 0 NOT NULL,
    metadata jsonb DEFAULT '{}'::jsonb NOT NULL,
    created_at timestamp with time zone DEFAULT now() NOT NULL,
    updated_at timestamp with time zone DEFAULT now() NOT NULL,
    CONSTRAINT credential_inventory_consecutive_failures_check CHECK ((consecutive_failures >= 0)),
    CONSTRAINT credential_inventory_metadata_check CHECK ((jsonb_typeof(metadata) = 'object'::text)),
    CONSTRAINT credential_inventory_provider_check CHECK ((provider = ANY (ARRAY['openai'::text, 'anthropic'::text, 'gemini'::text, 'xai'::text, 'moonshot'::text, 'antigravity'::text, 'gemini-cli'::text, 'codex'::text, 'claude'::text]))),
    CONSTRAINT credential_inventory_status_check CHECK ((status = ANY (ARRAY['HEALTHY'::text, 'DEGRADED'::text, 'CRITICAL'::text, 'EXPIRED'::text, 'SUSPENDED'::text])))
);


--
-- Name: LiteLLM_ModelTable id; Type: DEFAULT; Schema: public; Owner: -
--

ALTER TABLE ONLY public."LiteLLM_ModelTable" ALTER COLUMN id SET DEFAULT nextval('public."LiteLLM_ModelTable_id_seq"'::regclass);


--
-- Name: LiteLLM_AccessGroupTable LiteLLM_AccessGroupTable_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public."LiteLLM_AccessGroupTable"
    ADD CONSTRAINT "LiteLLM_AccessGroupTable_pkey" PRIMARY KEY (access_group_id);


--
-- Name: LiteLLM_AdaptiveRouterSession LiteLLM_AdaptiveRouterSession_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public."LiteLLM_AdaptiveRouterSession"
    ADD CONSTRAINT "LiteLLM_AdaptiveRouterSession_pkey" PRIMARY KEY (session_id, router_name, model_name);


--
-- Name: LiteLLM_AdaptiveRouterState LiteLLM_AdaptiveRouterState_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public."LiteLLM_AdaptiveRouterState"
    ADD CONSTRAINT "LiteLLM_AdaptiveRouterState_pkey" PRIMARY KEY (router_name, request_type, model_name);


--
-- Name: LiteLLM_AgentsTable LiteLLM_AgentsTable_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public."LiteLLM_AgentsTable"
    ADD CONSTRAINT "LiteLLM_AgentsTable_pkey" PRIMARY KEY (agent_id);


--
-- Name: LiteLLM_AuditLog LiteLLM_AuditLog_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public."LiteLLM_AuditLog"
    ADD CONSTRAINT "LiteLLM_AuditLog_pkey" PRIMARY KEY (id);


--
-- Name: LiteLLM_BudgetTable LiteLLM_BudgetTable_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public."LiteLLM_BudgetTable"
    ADD CONSTRAINT "LiteLLM_BudgetTable_pkey" PRIMARY KEY (budget_id);


--
-- Name: LiteLLM_CacheConfig LiteLLM_CacheConfig_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public."LiteLLM_CacheConfig"
    ADD CONSTRAINT "LiteLLM_CacheConfig_pkey" PRIMARY KEY (id);


--
-- Name: LiteLLM_ClaudeCodePluginTable LiteLLM_ClaudeCodePluginTable_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public."LiteLLM_ClaudeCodePluginTable"
    ADD CONSTRAINT "LiteLLM_ClaudeCodePluginTable_pkey" PRIMARY KEY (id);


--
-- Name: LiteLLM_ConfigOverrides LiteLLM_ConfigOverrides_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public."LiteLLM_ConfigOverrides"
    ADD CONSTRAINT "LiteLLM_ConfigOverrides_pkey" PRIMARY KEY (config_type);


--
-- Name: LiteLLM_Config LiteLLM_Config_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public."LiteLLM_Config"
    ADD CONSTRAINT "LiteLLM_Config_pkey" PRIMARY KEY (param_name);


--
-- Name: LiteLLM_CredentialsTable LiteLLM_CredentialsTable_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public."LiteLLM_CredentialsTable"
    ADD CONSTRAINT "LiteLLM_CredentialsTable_pkey" PRIMARY KEY (credential_id);


--
-- Name: LiteLLM_CronJob LiteLLM_CronJob_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public."LiteLLM_CronJob"
    ADD CONSTRAINT "LiteLLM_CronJob_pkey" PRIMARY KEY (cronjob_id);


--
-- Name: LiteLLM_DailyAgentSpend LiteLLM_DailyAgentSpend_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public."LiteLLM_DailyAgentSpend"
    ADD CONSTRAINT "LiteLLM_DailyAgentSpend_pkey" PRIMARY KEY (id);


--
-- Name: LiteLLM_DailyEndUserSpend LiteLLM_DailyEndUserSpend_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public."LiteLLM_DailyEndUserSpend"
    ADD CONSTRAINT "LiteLLM_DailyEndUserSpend_pkey" PRIMARY KEY (id);


--
-- Name: LiteLLM_DailyGuardrailMetrics LiteLLM_DailyGuardrailMetrics_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public."LiteLLM_DailyGuardrailMetrics"
    ADD CONSTRAINT "LiteLLM_DailyGuardrailMetrics_pkey" PRIMARY KEY (guardrail_id, date);


--
-- Name: LiteLLM_DailyOrganizationSpend LiteLLM_DailyOrganizationSpend_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public."LiteLLM_DailyOrganizationSpend"
    ADD CONSTRAINT "LiteLLM_DailyOrganizationSpend_pkey" PRIMARY KEY (id);


--
-- Name: LiteLLM_DailyPolicyMetrics LiteLLM_DailyPolicyMetrics_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public."LiteLLM_DailyPolicyMetrics"
    ADD CONSTRAINT "LiteLLM_DailyPolicyMetrics_pkey" PRIMARY KEY (policy_id, date);


--
-- Name: LiteLLM_DailyTagSpend LiteLLM_DailyTagSpend_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public."LiteLLM_DailyTagSpend"
    ADD CONSTRAINT "LiteLLM_DailyTagSpend_pkey" PRIMARY KEY (id);


--
-- Name: LiteLLM_DailyTeamSpend LiteLLM_DailyTeamSpend_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public."LiteLLM_DailyTeamSpend"
    ADD CONSTRAINT "LiteLLM_DailyTeamSpend_pkey" PRIMARY KEY (id);


--
-- Name: LiteLLM_DailyUserSpend LiteLLM_DailyUserSpend_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public."LiteLLM_DailyUserSpend"
    ADD CONSTRAINT "LiteLLM_DailyUserSpend_pkey" PRIMARY KEY (id);


--
-- Name: LiteLLM_DeletedTeamTable LiteLLM_DeletedTeamTable_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public."LiteLLM_DeletedTeamTable"
    ADD CONSTRAINT "LiteLLM_DeletedTeamTable_pkey" PRIMARY KEY (id);


--
-- Name: LiteLLM_DeletedVerificationToken LiteLLM_DeletedVerificationToken_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public."LiteLLM_DeletedVerificationToken"
    ADD CONSTRAINT "LiteLLM_DeletedVerificationToken_pkey" PRIMARY KEY (id);


--
-- Name: LiteLLM_DeprecatedVerificationToken LiteLLM_DeprecatedVerificationToken_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public."LiteLLM_DeprecatedVerificationToken"
    ADD CONSTRAINT "LiteLLM_DeprecatedVerificationToken_pkey" PRIMARY KEY (id);


--
-- Name: LiteLLM_EndUserTable LiteLLM_EndUserTable_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public."LiteLLM_EndUserTable"
    ADD CONSTRAINT "LiteLLM_EndUserTable_pkey" PRIMARY KEY (user_id);


--
-- Name: LiteLLM_ErrorLogs LiteLLM_ErrorLogs_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public."LiteLLM_ErrorLogs"
    ADD CONSTRAINT "LiteLLM_ErrorLogs_pkey" PRIMARY KEY (request_id);


--
-- Name: LiteLLM_GuardrailsTable LiteLLM_GuardrailsTable_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public."LiteLLM_GuardrailsTable"
    ADD CONSTRAINT "LiteLLM_GuardrailsTable_pkey" PRIMARY KEY (guardrail_id);


--
-- Name: LiteLLM_HealthCheckTable LiteLLM_HealthCheckTable_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public."LiteLLM_HealthCheckTable"
    ADD CONSTRAINT "LiteLLM_HealthCheckTable_pkey" PRIMARY KEY (health_check_id);


--
-- Name: LiteLLM_InvitationLink LiteLLM_InvitationLink_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public."LiteLLM_InvitationLink"
    ADD CONSTRAINT "LiteLLM_InvitationLink_pkey" PRIMARY KEY (id);


--
-- Name: LiteLLM_JWTKeyMapping LiteLLM_JWTKeyMapping_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public."LiteLLM_JWTKeyMapping"
    ADD CONSTRAINT "LiteLLM_JWTKeyMapping_pkey" PRIMARY KEY (id);


--
-- Name: LiteLLM_MCPServerTable LiteLLM_MCPServerTable_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public."LiteLLM_MCPServerTable"
    ADD CONSTRAINT "LiteLLM_MCPServerTable_pkey" PRIMARY KEY (server_id);


--
-- Name: LiteLLM_MCPToolsetTable LiteLLM_MCPToolsetTable_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public."LiteLLM_MCPToolsetTable"
    ADD CONSTRAINT "LiteLLM_MCPToolsetTable_pkey" PRIMARY KEY (toolset_id);


--
-- Name: LiteLLM_MCPUserCredentials LiteLLM_MCPUserCredentials_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public."LiteLLM_MCPUserCredentials"
    ADD CONSTRAINT "LiteLLM_MCPUserCredentials_pkey" PRIMARY KEY (id);


--
-- Name: LiteLLM_ManagedFileTable LiteLLM_ManagedFileTable_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public."LiteLLM_ManagedFileTable"
    ADD CONSTRAINT "LiteLLM_ManagedFileTable_pkey" PRIMARY KEY (id);


--
-- Name: LiteLLM_ManagedObjectTable LiteLLM_ManagedObjectTable_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public."LiteLLM_ManagedObjectTable"
    ADD CONSTRAINT "LiteLLM_ManagedObjectTable_pkey" PRIMARY KEY (id);


--
-- Name: LiteLLM_ManagedVectorStoreIndexTable LiteLLM_ManagedVectorStoreIndexTable_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public."LiteLLM_ManagedVectorStoreIndexTable"
    ADD CONSTRAINT "LiteLLM_ManagedVectorStoreIndexTable_pkey" PRIMARY KEY (id);


--
-- Name: LiteLLM_ManagedVectorStoreTable LiteLLM_ManagedVectorStoreTable_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public."LiteLLM_ManagedVectorStoreTable"
    ADD CONSTRAINT "LiteLLM_ManagedVectorStoreTable_pkey" PRIMARY KEY (id);


--
-- Name: LiteLLM_ManagedVectorStoresTable LiteLLM_ManagedVectorStoresTable_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public."LiteLLM_ManagedVectorStoresTable"
    ADD CONSTRAINT "LiteLLM_ManagedVectorStoresTable_pkey" PRIMARY KEY (vector_store_id);


--
-- Name: LiteLLM_MemoryTable LiteLLM_MemoryTable_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public."LiteLLM_MemoryTable"
    ADD CONSTRAINT "LiteLLM_MemoryTable_pkey" PRIMARY KEY (memory_id);


--
-- Name: LiteLLM_ModelTable LiteLLM_ModelTable_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public."LiteLLM_ModelTable"
    ADD CONSTRAINT "LiteLLM_ModelTable_pkey" PRIMARY KEY (id);


--
-- Name: LiteLLM_ObjectPermissionTable LiteLLM_ObjectPermissionTable_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public."LiteLLM_ObjectPermissionTable"
    ADD CONSTRAINT "LiteLLM_ObjectPermissionTable_pkey" PRIMARY KEY (object_permission_id);


--
-- Name: LiteLLM_OrganizationMembership LiteLLM_OrganizationMembership_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public."LiteLLM_OrganizationMembership"
    ADD CONSTRAINT "LiteLLM_OrganizationMembership_pkey" PRIMARY KEY (user_id, organization_id);


--
-- Name: LiteLLM_OrganizationTable LiteLLM_OrganizationTable_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public."LiteLLM_OrganizationTable"
    ADD CONSTRAINT "LiteLLM_OrganizationTable_pkey" PRIMARY KEY (organization_id);


--
-- Name: LiteLLM_PolicyAttachmentTable LiteLLM_PolicyAttachmentTable_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public."LiteLLM_PolicyAttachmentTable"
    ADD CONSTRAINT "LiteLLM_PolicyAttachmentTable_pkey" PRIMARY KEY (attachment_id);


--
-- Name: LiteLLM_PolicyTable LiteLLM_PolicyTable_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public."LiteLLM_PolicyTable"
    ADD CONSTRAINT "LiteLLM_PolicyTable_pkey" PRIMARY KEY (policy_id);


--
-- Name: LiteLLM_ProjectTable LiteLLM_ProjectTable_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public."LiteLLM_ProjectTable"
    ADD CONSTRAINT "LiteLLM_ProjectTable_pkey" PRIMARY KEY (project_id);


--
-- Name: LiteLLM_PromptTable LiteLLM_PromptTable_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public."LiteLLM_PromptTable"
    ADD CONSTRAINT "LiteLLM_PromptTable_pkey" PRIMARY KEY (id);


--
-- Name: LiteLLM_ProxyModelTable LiteLLM_ProxyModelTable_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public."LiteLLM_ProxyModelTable"
    ADD CONSTRAINT "LiteLLM_ProxyModelTable_pkey" PRIMARY KEY (model_id);


--
-- Name: LiteLLM_SSOConfig LiteLLM_SSOConfig_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public."LiteLLM_SSOConfig"
    ADD CONSTRAINT "LiteLLM_SSOConfig_pkey" PRIMARY KEY (id);


--
-- Name: LiteLLM_SearchToolsTable LiteLLM_SearchToolsTable_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public."LiteLLM_SearchToolsTable"
    ADD CONSTRAINT "LiteLLM_SearchToolsTable_pkey" PRIMARY KEY (search_tool_id);


--
-- Name: LiteLLM_SkillsTable LiteLLM_SkillsTable_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public."LiteLLM_SkillsTable"
    ADD CONSTRAINT "LiteLLM_SkillsTable_pkey" PRIMARY KEY (skill_id);


--
-- Name: LiteLLM_SpendLogGuardrailIndex LiteLLM_SpendLogGuardrailIndex_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public."LiteLLM_SpendLogGuardrailIndex"
    ADD CONSTRAINT "LiteLLM_SpendLogGuardrailIndex_pkey" PRIMARY KEY (request_id, guardrail_id);


--
-- Name: LiteLLM_SpendLogToolIndex LiteLLM_SpendLogToolIndex_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public."LiteLLM_SpendLogToolIndex"
    ADD CONSTRAINT "LiteLLM_SpendLogToolIndex_pkey" PRIMARY KEY (request_id, tool_name);


--
-- Name: LiteLLM_SpendLogs LiteLLM_SpendLogs_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public."LiteLLM_SpendLogs"
    ADD CONSTRAINT "LiteLLM_SpendLogs_pkey" PRIMARY KEY (request_id);


--
-- Name: LiteLLM_TagTable LiteLLM_TagTable_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public."LiteLLM_TagTable"
    ADD CONSTRAINT "LiteLLM_TagTable_pkey" PRIMARY KEY (tag_name);


--
-- Name: LiteLLM_TeamMembership LiteLLM_TeamMembership_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public."LiteLLM_TeamMembership"
    ADD CONSTRAINT "LiteLLM_TeamMembership_pkey" PRIMARY KEY (user_id, team_id);


--
-- Name: LiteLLM_TeamTable LiteLLM_TeamTable_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public."LiteLLM_TeamTable"
    ADD CONSTRAINT "LiteLLM_TeamTable_pkey" PRIMARY KEY (team_id);


--
-- Name: LiteLLM_ToolTable LiteLLM_ToolTable_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public."LiteLLM_ToolTable"
    ADD CONSTRAINT "LiteLLM_ToolTable_pkey" PRIMARY KEY (tool_id);


--
-- Name: LiteLLM_UISettings LiteLLM_UISettings_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public."LiteLLM_UISettings"
    ADD CONSTRAINT "LiteLLM_UISettings_pkey" PRIMARY KEY (id);


--
-- Name: LiteLLM_UserNotifications LiteLLM_UserNotifications_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public."LiteLLM_UserNotifications"
    ADD CONSTRAINT "LiteLLM_UserNotifications_pkey" PRIMARY KEY (request_id);


--
-- Name: LiteLLM_UserTable LiteLLM_UserTable_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public."LiteLLM_UserTable"
    ADD CONSTRAINT "LiteLLM_UserTable_pkey" PRIMARY KEY (user_id);


--
-- Name: LiteLLM_VerificationToken LiteLLM_VerificationToken_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public."LiteLLM_VerificationToken"
    ADD CONSTRAINT "LiteLLM_VerificationToken_pkey" PRIMARY KEY (token);


--
-- Name: LiteLLM_WorkflowEvent LiteLLM_WorkflowEvent_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public."LiteLLM_WorkflowEvent"
    ADD CONSTRAINT "LiteLLM_WorkflowEvent_pkey" PRIMARY KEY (event_id);


--
-- Name: LiteLLM_WorkflowMessage LiteLLM_WorkflowMessage_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public."LiteLLM_WorkflowMessage"
    ADD CONSTRAINT "LiteLLM_WorkflowMessage_pkey" PRIMARY KEY (message_id);


--
-- Name: LiteLLM_WorkflowRun LiteLLM_WorkflowRun_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public."LiteLLM_WorkflowRun"
    ADD CONSTRAINT "LiteLLM_WorkflowRun_pkey" PRIMARY KEY (run_id);


--
-- Name: _prisma_migrations _prisma_migrations_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public._prisma_migrations
    ADD CONSTRAINT _prisma_migrations_pkey PRIMARY KEY (id);


--
-- Name: credential_inventory credential_inventory_key_fingerprint_key; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.credential_inventory
    ADD CONSTRAINT credential_inventory_key_fingerprint_key UNIQUE (key_fingerprint);


--
-- Name: credential_inventory credential_inventory_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.credential_inventory
    ADD CONSTRAINT credential_inventory_pkey PRIMARY KEY (credential_id);


--
-- Name: LiteLLM_AccessGroupTable_access_group_name_key; Type: INDEX; Schema: public; Owner: -
--

CREATE UNIQUE INDEX "LiteLLM_AccessGroupTable_access_group_name_key" ON public."LiteLLM_AccessGroupTable" USING btree (access_group_name);


--
-- Name: LiteLLM_AgentsTable_agent_name_key; Type: INDEX; Schema: public; Owner: -
--

CREATE UNIQUE INDEX "LiteLLM_AgentsTable_agent_name_key" ON public."LiteLLM_AgentsTable" USING btree (agent_name);


--
-- Name: LiteLLM_ClaudeCodePluginTable_name_key; Type: INDEX; Schema: public; Owner: -
--

CREATE UNIQUE INDEX "LiteLLM_ClaudeCodePluginTable_name_key" ON public."LiteLLM_ClaudeCodePluginTable" USING btree (name);


--
-- Name: LiteLLM_CredentialsTable_credential_name_key; Type: INDEX; Schema: public; Owner: -
--

CREATE UNIQUE INDEX "LiteLLM_CredentialsTable_credential_name_key" ON public."LiteLLM_CredentialsTable" USING btree (credential_name);


--
-- Name: LiteLLM_DailyAgentSpend_agent_id_date_api_key_model_custom__key; Type: INDEX; Schema: public; Owner: -
--

CREATE UNIQUE INDEX "LiteLLM_DailyAgentSpend_agent_id_date_api_key_model_custom__key" ON public."LiteLLM_DailyAgentSpend" USING btree (agent_id, date, api_key, model, custom_llm_provider, mcp_namespaced_tool_name, endpoint);


--
-- Name: LiteLLM_DailyAgentSpend_agent_id_date_idx; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX "LiteLLM_DailyAgentSpend_agent_id_date_idx" ON public."LiteLLM_DailyAgentSpend" USING btree (agent_id, date);


--
-- Name: LiteLLM_DailyAgentSpend_api_key_idx; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX "LiteLLM_DailyAgentSpend_api_key_idx" ON public."LiteLLM_DailyAgentSpend" USING btree (api_key);


--
-- Name: LiteLLM_DailyAgentSpend_date_idx; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX "LiteLLM_DailyAgentSpend_date_idx" ON public."LiteLLM_DailyAgentSpend" USING btree (date);


--
-- Name: LiteLLM_DailyAgentSpend_endpoint_idx; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX "LiteLLM_DailyAgentSpend_endpoint_idx" ON public."LiteLLM_DailyAgentSpend" USING btree (endpoint);


--
-- Name: LiteLLM_DailyAgentSpend_mcp_namespaced_tool_name_idx; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX "LiteLLM_DailyAgentSpend_mcp_namespaced_tool_name_idx" ON public."LiteLLM_DailyAgentSpend" USING btree (mcp_namespaced_tool_name);


--
-- Name: LiteLLM_DailyAgentSpend_model_idx; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX "LiteLLM_DailyAgentSpend_model_idx" ON public."LiteLLM_DailyAgentSpend" USING btree (model);


--
-- Name: LiteLLM_DailyEndUserSpend_api_key_idx; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX "LiteLLM_DailyEndUserSpend_api_key_idx" ON public."LiteLLM_DailyEndUserSpend" USING btree (api_key);


--
-- Name: LiteLLM_DailyEndUserSpend_date_idx; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX "LiteLLM_DailyEndUserSpend_date_idx" ON public."LiteLLM_DailyEndUserSpend" USING btree (date);


--
-- Name: LiteLLM_DailyEndUserSpend_end_user_id_date_api_key_model_cu_key; Type: INDEX; Schema: public; Owner: -
--

CREATE UNIQUE INDEX "LiteLLM_DailyEndUserSpend_end_user_id_date_api_key_model_cu_key" ON public."LiteLLM_DailyEndUserSpend" USING btree (end_user_id, date, api_key, model, custom_llm_provider, mcp_namespaced_tool_name, endpoint);


--
-- Name: LiteLLM_DailyEndUserSpend_end_user_id_date_idx; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX "LiteLLM_DailyEndUserSpend_end_user_id_date_idx" ON public."LiteLLM_DailyEndUserSpend" USING btree (end_user_id, date);


--
-- Name: LiteLLM_DailyEndUserSpend_endpoint_idx; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX "LiteLLM_DailyEndUserSpend_endpoint_idx" ON public."LiteLLM_DailyEndUserSpend" USING btree (endpoint);


--
-- Name: LiteLLM_DailyEndUserSpend_mcp_namespaced_tool_name_idx; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX "LiteLLM_DailyEndUserSpend_mcp_namespaced_tool_name_idx" ON public."LiteLLM_DailyEndUserSpend" USING btree (mcp_namespaced_tool_name);


--
-- Name: LiteLLM_DailyEndUserSpend_model_idx; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX "LiteLLM_DailyEndUserSpend_model_idx" ON public."LiteLLM_DailyEndUserSpend" USING btree (model);


--
-- Name: LiteLLM_DailyGuardrailMetrics_date_idx; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX "LiteLLM_DailyGuardrailMetrics_date_idx" ON public."LiteLLM_DailyGuardrailMetrics" USING btree (date);


--
-- Name: LiteLLM_DailyGuardrailMetrics_guardrail_id_idx; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX "LiteLLM_DailyGuardrailMetrics_guardrail_id_idx" ON public."LiteLLM_DailyGuardrailMetrics" USING btree (guardrail_id);


--
-- Name: LiteLLM_DailyOrganizationSpend_api_key_idx; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX "LiteLLM_DailyOrganizationSpend_api_key_idx" ON public."LiteLLM_DailyOrganizationSpend" USING btree (api_key);


--
-- Name: LiteLLM_DailyOrganizationSpend_date_idx; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX "LiteLLM_DailyOrganizationSpend_date_idx" ON public."LiteLLM_DailyOrganizationSpend" USING btree (date);


--
-- Name: LiteLLM_DailyOrganizationSpend_endpoint_idx; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX "LiteLLM_DailyOrganizationSpend_endpoint_idx" ON public."LiteLLM_DailyOrganizationSpend" USING btree (endpoint);


--
-- Name: LiteLLM_DailyOrganizationSpend_mcp_namespaced_tool_name_idx; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX "LiteLLM_DailyOrganizationSpend_mcp_namespaced_tool_name_idx" ON public."LiteLLM_DailyOrganizationSpend" USING btree (mcp_namespaced_tool_name);


--
-- Name: LiteLLM_DailyOrganizationSpend_model_idx; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX "LiteLLM_DailyOrganizationSpend_model_idx" ON public."LiteLLM_DailyOrganizationSpend" USING btree (model);


--
-- Name: LiteLLM_DailyOrganizationSpend_organization_id_date_api_key_key; Type: INDEX; Schema: public; Owner: -
--

CREATE UNIQUE INDEX "LiteLLM_DailyOrganizationSpend_organization_id_date_api_key_key" ON public."LiteLLM_DailyOrganizationSpend" USING btree (organization_id, date, api_key, model, custom_llm_provider, mcp_namespaced_tool_name, endpoint);


--
-- Name: LiteLLM_DailyOrganizationSpend_organization_id_date_idx; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX "LiteLLM_DailyOrganizationSpend_organization_id_date_idx" ON public."LiteLLM_DailyOrganizationSpend" USING btree (organization_id, date);


--
-- Name: LiteLLM_DailyPolicyMetrics_date_idx; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX "LiteLLM_DailyPolicyMetrics_date_idx" ON public."LiteLLM_DailyPolicyMetrics" USING btree (date);


--
-- Name: LiteLLM_DailyPolicyMetrics_policy_id_idx; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX "LiteLLM_DailyPolicyMetrics_policy_id_idx" ON public."LiteLLM_DailyPolicyMetrics" USING btree (policy_id);


--
-- Name: LiteLLM_DailyTagSpend_api_key_idx; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX "LiteLLM_DailyTagSpend_api_key_idx" ON public."LiteLLM_DailyTagSpend" USING btree (api_key);


--
-- Name: LiteLLM_DailyTagSpend_date_idx; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX "LiteLLM_DailyTagSpend_date_idx" ON public."LiteLLM_DailyTagSpend" USING btree (date);


--
-- Name: LiteLLM_DailyTagSpend_endpoint_idx; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX "LiteLLM_DailyTagSpend_endpoint_idx" ON public."LiteLLM_DailyTagSpend" USING btree (endpoint);


--
-- Name: LiteLLM_DailyTagSpend_mcp_namespaced_tool_name_idx; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX "LiteLLM_DailyTagSpend_mcp_namespaced_tool_name_idx" ON public."LiteLLM_DailyTagSpend" USING btree (mcp_namespaced_tool_name);


--
-- Name: LiteLLM_DailyTagSpend_model_idx; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX "LiteLLM_DailyTagSpend_model_idx" ON public."LiteLLM_DailyTagSpend" USING btree (model);


--
-- Name: LiteLLM_DailyTagSpend_tag_date_api_key_model_custom_llm_pro_key; Type: INDEX; Schema: public; Owner: -
--

CREATE UNIQUE INDEX "LiteLLM_DailyTagSpend_tag_date_api_key_model_custom_llm_pro_key" ON public."LiteLLM_DailyTagSpend" USING btree (tag, date, api_key, model, custom_llm_provider, mcp_namespaced_tool_name, endpoint);


--
-- Name: LiteLLM_DailyTagSpend_tag_date_idx; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX "LiteLLM_DailyTagSpend_tag_date_idx" ON public."LiteLLM_DailyTagSpend" USING btree (tag, date);


--
-- Name: LiteLLM_DailyTeamSpend_api_key_idx; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX "LiteLLM_DailyTeamSpend_api_key_idx" ON public."LiteLLM_DailyTeamSpend" USING btree (api_key);


--
-- Name: LiteLLM_DailyTeamSpend_date_idx; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX "LiteLLM_DailyTeamSpend_date_idx" ON public."LiteLLM_DailyTeamSpend" USING btree (date);


--
-- Name: LiteLLM_DailyTeamSpend_endpoint_idx; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX "LiteLLM_DailyTeamSpend_endpoint_idx" ON public."LiteLLM_DailyTeamSpend" USING btree (endpoint);


--
-- Name: LiteLLM_DailyTeamSpend_mcp_namespaced_tool_name_idx; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX "LiteLLM_DailyTeamSpend_mcp_namespaced_tool_name_idx" ON public."LiteLLM_DailyTeamSpend" USING btree (mcp_namespaced_tool_name);


--
-- Name: LiteLLM_DailyTeamSpend_model_idx; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX "LiteLLM_DailyTeamSpend_model_idx" ON public."LiteLLM_DailyTeamSpend" USING btree (model);


--
-- Name: LiteLLM_DailyTeamSpend_team_id_date_api_key_model_custom_ll_key; Type: INDEX; Schema: public; Owner: -
--

CREATE UNIQUE INDEX "LiteLLM_DailyTeamSpend_team_id_date_api_key_model_custom_ll_key" ON public."LiteLLM_DailyTeamSpend" USING btree (team_id, date, api_key, model, custom_llm_provider, mcp_namespaced_tool_name, endpoint);


--
-- Name: LiteLLM_DailyTeamSpend_team_id_date_idx; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX "LiteLLM_DailyTeamSpend_team_id_date_idx" ON public."LiteLLM_DailyTeamSpend" USING btree (team_id, date);


--
-- Name: LiteLLM_DailyUserSpend_api_key_idx; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX "LiteLLM_DailyUserSpend_api_key_idx" ON public."LiteLLM_DailyUserSpend" USING btree (api_key);


--
-- Name: LiteLLM_DailyUserSpend_date_idx; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX "LiteLLM_DailyUserSpend_date_idx" ON public."LiteLLM_DailyUserSpend" USING btree (date);


--
-- Name: LiteLLM_DailyUserSpend_endpoint_idx; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX "LiteLLM_DailyUserSpend_endpoint_idx" ON public."LiteLLM_DailyUserSpend" USING btree (endpoint);


--
-- Name: LiteLLM_DailyUserSpend_mcp_namespaced_tool_name_idx; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX "LiteLLM_DailyUserSpend_mcp_namespaced_tool_name_idx" ON public."LiteLLM_DailyUserSpend" USING btree (mcp_namespaced_tool_name);


--
-- Name: LiteLLM_DailyUserSpend_model_idx; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX "LiteLLM_DailyUserSpend_model_idx" ON public."LiteLLM_DailyUserSpend" USING btree (model);


--
-- Name: LiteLLM_DailyUserSpend_user_id_date_api_key_model_custom_ll_key; Type: INDEX; Schema: public; Owner: -
--

CREATE UNIQUE INDEX "LiteLLM_DailyUserSpend_user_id_date_api_key_model_custom_ll_key" ON public."LiteLLM_DailyUserSpend" USING btree (user_id, date, api_key, model, custom_llm_provider, mcp_namespaced_tool_name, endpoint);


--
-- Name: LiteLLM_DailyUserSpend_user_id_date_idx; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX "LiteLLM_DailyUserSpend_user_id_date_idx" ON public."LiteLLM_DailyUserSpend" USING btree (user_id, date);


--
-- Name: LiteLLM_DeletedTeamTable_created_at_idx; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX "LiteLLM_DeletedTeamTable_created_at_idx" ON public."LiteLLM_DeletedTeamTable" USING btree (created_at);


--
-- Name: LiteLLM_DeletedTeamTable_deleted_at_idx; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX "LiteLLM_DeletedTeamTable_deleted_at_idx" ON public."LiteLLM_DeletedTeamTable" USING btree (deleted_at);


--
-- Name: LiteLLM_DeletedTeamTable_organization_id_idx; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX "LiteLLM_DeletedTeamTable_organization_id_idx" ON public."LiteLLM_DeletedTeamTable" USING btree (organization_id);


--
-- Name: LiteLLM_DeletedTeamTable_team_alias_idx; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX "LiteLLM_DeletedTeamTable_team_alias_idx" ON public."LiteLLM_DeletedTeamTable" USING btree (team_alias);


--
-- Name: LiteLLM_DeletedTeamTable_team_id_idx; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX "LiteLLM_DeletedTeamTable_team_id_idx" ON public."LiteLLM_DeletedTeamTable" USING btree (team_id);


--
-- Name: LiteLLM_DeletedVerificationToken_created_at_idx; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX "LiteLLM_DeletedVerificationToken_created_at_idx" ON public."LiteLLM_DeletedVerificationToken" USING btree (created_at);


--
-- Name: LiteLLM_DeletedVerificationToken_deleted_at_idx; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX "LiteLLM_DeletedVerificationToken_deleted_at_idx" ON public."LiteLLM_DeletedVerificationToken" USING btree (deleted_at);


--
-- Name: LiteLLM_DeletedVerificationToken_key_alias_idx; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX "LiteLLM_DeletedVerificationToken_key_alias_idx" ON public."LiteLLM_DeletedVerificationToken" USING btree (key_alias);


--
-- Name: LiteLLM_DeletedVerificationToken_organization_id_idx; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX "LiteLLM_DeletedVerificationToken_organization_id_idx" ON public."LiteLLM_DeletedVerificationToken" USING btree (organization_id);


--
-- Name: LiteLLM_DeletedVerificationToken_team_id_idx; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX "LiteLLM_DeletedVerificationToken_team_id_idx" ON public."LiteLLM_DeletedVerificationToken" USING btree (team_id);


--
-- Name: LiteLLM_DeletedVerificationToken_token_idx; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX "LiteLLM_DeletedVerificationToken_token_idx" ON public."LiteLLM_DeletedVerificationToken" USING btree (token);


--
-- Name: LiteLLM_DeletedVerificationToken_user_id_idx; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX "LiteLLM_DeletedVerificationToken_user_id_idx" ON public."LiteLLM_DeletedVerificationToken" USING btree (user_id);


--
-- Name: LiteLLM_DeprecatedVerificationToken_revoke_at_idx; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX "LiteLLM_DeprecatedVerificationToken_revoke_at_idx" ON public."LiteLLM_DeprecatedVerificationToken" USING btree (revoke_at);


--
-- Name: LiteLLM_DeprecatedVerificationToken_token_key; Type: INDEX; Schema: public; Owner: -
--

CREATE UNIQUE INDEX "LiteLLM_DeprecatedVerificationToken_token_key" ON public."LiteLLM_DeprecatedVerificationToken" USING btree (token);


--
-- Name: LiteLLM_DeprecatedVerificationToken_token_revoke_at_idx; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX "LiteLLM_DeprecatedVerificationToken_token_revoke_at_idx" ON public."LiteLLM_DeprecatedVerificationToken" USING btree (token, revoke_at);


--
-- Name: LiteLLM_GuardrailsTable_guardrail_name_key; Type: INDEX; Schema: public; Owner: -
--

CREATE UNIQUE INDEX "LiteLLM_GuardrailsTable_guardrail_name_key" ON public."LiteLLM_GuardrailsTable" USING btree (guardrail_name);


--
-- Name: LiteLLM_GuardrailsTable_status_idx; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX "LiteLLM_GuardrailsTable_status_idx" ON public."LiteLLM_GuardrailsTable" USING btree (status);


--
-- Name: LiteLLM_HealthCheckTable_checked_at_idx; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX "LiteLLM_HealthCheckTable_checked_at_idx" ON public."LiteLLM_HealthCheckTable" USING btree (checked_at);


--
-- Name: LiteLLM_HealthCheckTable_model_id_model_name_checked_at_idx; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX "LiteLLM_HealthCheckTable_model_id_model_name_checked_at_idx" ON public."LiteLLM_HealthCheckTable" USING btree (model_id, model_name, checked_at DESC);


--
-- Name: LiteLLM_HealthCheckTable_model_name_idx; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX "LiteLLM_HealthCheckTable_model_name_idx" ON public."LiteLLM_HealthCheckTable" USING btree (model_name);


--
-- Name: LiteLLM_HealthCheckTable_status_idx; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX "LiteLLM_HealthCheckTable_status_idx" ON public."LiteLLM_HealthCheckTable" USING btree (status);


--
-- Name: LiteLLM_JWTKeyMapping_jwt_claim_name_jwt_claim_value_is_act_idx; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX "LiteLLM_JWTKeyMapping_jwt_claim_name_jwt_claim_value_is_act_idx" ON public."LiteLLM_JWTKeyMapping" USING btree (jwt_claim_name, jwt_claim_value, is_active);


--
-- Name: LiteLLM_JWTKeyMapping_jwt_claim_name_jwt_claim_value_key; Type: INDEX; Schema: public; Owner: -
--

CREATE UNIQUE INDEX "LiteLLM_JWTKeyMapping_jwt_claim_name_jwt_claim_value_key" ON public."LiteLLM_JWTKeyMapping" USING btree (jwt_claim_name, jwt_claim_value);


--
-- Name: LiteLLM_MCPServerTable_approval_status_idx; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX "LiteLLM_MCPServerTable_approval_status_idx" ON public."LiteLLM_MCPServerTable" USING btree (approval_status);


--
-- Name: LiteLLM_MCPToolsetTable_toolset_name_key; Type: INDEX; Schema: public; Owner: -
--

CREATE UNIQUE INDEX "LiteLLM_MCPToolsetTable_toolset_name_key" ON public."LiteLLM_MCPToolsetTable" USING btree (toolset_name);


--
-- Name: LiteLLM_MCPUserCredentials_user_id_server_id_key; Type: INDEX; Schema: public; Owner: -
--

CREATE UNIQUE INDEX "LiteLLM_MCPUserCredentials_user_id_server_id_key" ON public."LiteLLM_MCPUserCredentials" USING btree (user_id, server_id);


--
-- Name: LiteLLM_ManagedFileTable_team_id_created_at_idx; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX "LiteLLM_ManagedFileTable_team_id_created_at_idx" ON public."LiteLLM_ManagedFileTable" USING btree (team_id, created_at DESC);


--
-- Name: LiteLLM_ManagedFileTable_unified_file_id_idx; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX "LiteLLM_ManagedFileTable_unified_file_id_idx" ON public."LiteLLM_ManagedFileTable" USING btree (unified_file_id);


--
-- Name: LiteLLM_ManagedFileTable_unified_file_id_key; Type: INDEX; Schema: public; Owner: -
--

CREATE UNIQUE INDEX "LiteLLM_ManagedFileTable_unified_file_id_key" ON public."LiteLLM_ManagedFileTable" USING btree (unified_file_id);


--
-- Name: LiteLLM_ManagedObjectTable_model_object_id_idx; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX "LiteLLM_ManagedObjectTable_model_object_id_idx" ON public."LiteLLM_ManagedObjectTable" USING btree (model_object_id);


--
-- Name: LiteLLM_ManagedObjectTable_model_object_id_key; Type: INDEX; Schema: public; Owner: -
--

CREATE UNIQUE INDEX "LiteLLM_ManagedObjectTable_model_object_id_key" ON public."LiteLLM_ManagedObjectTable" USING btree (model_object_id);


--
-- Name: LiteLLM_ManagedObjectTable_team_id_created_at_idx; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX "LiteLLM_ManagedObjectTable_team_id_created_at_idx" ON public."LiteLLM_ManagedObjectTable" USING btree (team_id, created_at DESC);


--
-- Name: LiteLLM_ManagedObjectTable_unified_object_id_idx; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX "LiteLLM_ManagedObjectTable_unified_object_id_idx" ON public."LiteLLM_ManagedObjectTable" USING btree (unified_object_id);


--
-- Name: LiteLLM_ManagedObjectTable_unified_object_id_key; Type: INDEX; Schema: public; Owner: -
--

CREATE UNIQUE INDEX "LiteLLM_ManagedObjectTable_unified_object_id_key" ON public."LiteLLM_ManagedObjectTable" USING btree (unified_object_id);


--
-- Name: LiteLLM_ManagedVectorStoreIndexTable_index_name_key; Type: INDEX; Schema: public; Owner: -
--

CREATE UNIQUE INDEX "LiteLLM_ManagedVectorStoreIndexTable_index_name_key" ON public."LiteLLM_ManagedVectorStoreIndexTable" USING btree (index_name);


--
-- Name: LiteLLM_ManagedVectorStoreTable_team_id_created_at_idx; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX "LiteLLM_ManagedVectorStoreTable_team_id_created_at_idx" ON public."LiteLLM_ManagedVectorStoreTable" USING btree (team_id, created_at DESC);


--
-- Name: LiteLLM_ManagedVectorStoreTable_unified_resource_id_idx; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX "LiteLLM_ManagedVectorStoreTable_unified_resource_id_idx" ON public."LiteLLM_ManagedVectorStoreTable" USING btree (unified_resource_id);


--
-- Name: LiteLLM_ManagedVectorStoreTable_unified_resource_id_key; Type: INDEX; Schema: public; Owner: -
--

CREATE UNIQUE INDEX "LiteLLM_ManagedVectorStoreTable_unified_resource_id_key" ON public."LiteLLM_ManagedVectorStoreTable" USING btree (unified_resource_id);


--
-- Name: LiteLLM_ManagedVectorStoresTable_team_id_idx; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX "LiteLLM_ManagedVectorStoresTable_team_id_idx" ON public."LiteLLM_ManagedVectorStoresTable" USING btree (team_id);


--
-- Name: LiteLLM_ManagedVectorStoresTable_user_id_idx; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX "LiteLLM_ManagedVectorStoresTable_user_id_idx" ON public."LiteLLM_ManagedVectorStoresTable" USING btree (user_id);


--
-- Name: LiteLLM_MemoryTable_key_key; Type: INDEX; Schema: public; Owner: -
--

CREATE UNIQUE INDEX "LiteLLM_MemoryTable_key_key" ON public."LiteLLM_MemoryTable" USING btree (key);


--
-- Name: LiteLLM_MemoryTable_team_id_idx; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX "LiteLLM_MemoryTable_team_id_idx" ON public."LiteLLM_MemoryTable" USING btree (team_id);


--
-- Name: LiteLLM_MemoryTable_user_id_idx; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX "LiteLLM_MemoryTable_user_id_idx" ON public."LiteLLM_MemoryTable" USING btree (user_id);


--
-- Name: LiteLLM_OrganizationMembership_user_id_organization_id_key; Type: INDEX; Schema: public; Owner: -
--

CREATE UNIQUE INDEX "LiteLLM_OrganizationMembership_user_id_organization_id_key" ON public."LiteLLM_OrganizationMembership" USING btree (user_id, organization_id);


--
-- Name: LiteLLM_PolicyTable_policy_name_version_number_key; Type: INDEX; Schema: public; Owner: -
--

CREATE UNIQUE INDEX "LiteLLM_PolicyTable_policy_name_version_number_key" ON public."LiteLLM_PolicyTable" USING btree (policy_name, version_number);


--
-- Name: LiteLLM_PolicyTable_policy_name_version_status_idx; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX "LiteLLM_PolicyTable_policy_name_version_status_idx" ON public."LiteLLM_PolicyTable" USING btree (policy_name, version_status);


--
-- Name: LiteLLM_PromptTable_prompt_id_environment_idx; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX "LiteLLM_PromptTable_prompt_id_environment_idx" ON public."LiteLLM_PromptTable" USING btree (prompt_id, environment);


--
-- Name: LiteLLM_PromptTable_prompt_id_idx; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX "LiteLLM_PromptTable_prompt_id_idx" ON public."LiteLLM_PromptTable" USING btree (prompt_id);


--
-- Name: LiteLLM_PromptTable_prompt_id_version_environment_key; Type: INDEX; Schema: public; Owner: -
--

CREATE UNIQUE INDEX "LiteLLM_PromptTable_prompt_id_version_environment_key" ON public."LiteLLM_PromptTable" USING btree (prompt_id, version, environment);


--
-- Name: LiteLLM_SearchToolsTable_search_tool_name_key; Type: INDEX; Schema: public; Owner: -
--

CREATE UNIQUE INDEX "LiteLLM_SearchToolsTable_search_tool_name_key" ON public."LiteLLM_SearchToolsTable" USING btree (search_tool_name);


--
-- Name: LiteLLM_SpendLogGuardrailIndex_guardrail_id_start_time_idx; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX "LiteLLM_SpendLogGuardrailIndex_guardrail_id_start_time_idx" ON public."LiteLLM_SpendLogGuardrailIndex" USING btree (guardrail_id, start_time);


--
-- Name: LiteLLM_SpendLogGuardrailIndex_policy_id_start_time_idx; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX "LiteLLM_SpendLogGuardrailIndex_policy_id_start_time_idx" ON public."LiteLLM_SpendLogGuardrailIndex" USING btree (policy_id, start_time);


--
-- Name: LiteLLM_SpendLogToolIndex_tool_name_start_time_idx; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX "LiteLLM_SpendLogToolIndex_tool_name_start_time_idx" ON public."LiteLLM_SpendLogToolIndex" USING btree (tool_name, start_time);


--
-- Name: LiteLLM_SpendLogs_end_user_idx; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX "LiteLLM_SpendLogs_end_user_idx" ON public."LiteLLM_SpendLogs" USING btree (end_user);


--
-- Name: LiteLLM_SpendLogs_session_id_idx; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX "LiteLLM_SpendLogs_session_id_idx" ON public."LiteLLM_SpendLogs" USING btree (session_id);


--
-- Name: LiteLLM_SpendLogs_startTime_idx; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX "LiteLLM_SpendLogs_startTime_idx" ON public."LiteLLM_SpendLogs" USING btree ("startTime");


--
-- Name: LiteLLM_SpendLogs_startTime_request_id_idx; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX "LiteLLM_SpendLogs_startTime_request_id_idx" ON public."LiteLLM_SpendLogs" USING btree ("startTime", request_id);


--
-- Name: LiteLLM_TeamTable_created_at_idx; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX "LiteLLM_TeamTable_created_at_idx" ON public."LiteLLM_TeamTable" USING btree (created_at);


--
-- Name: LiteLLM_TeamTable_model_id_key; Type: INDEX; Schema: public; Owner: -
--

CREATE UNIQUE INDEX "LiteLLM_TeamTable_model_id_key" ON public."LiteLLM_TeamTable" USING btree (model_id);


--
-- Name: LiteLLM_TeamTable_organization_id_idx; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX "LiteLLM_TeamTable_organization_id_idx" ON public."LiteLLM_TeamTable" USING btree (organization_id);


--
-- Name: LiteLLM_TeamTable_team_alias_idx; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX "LiteLLM_TeamTable_team_alias_idx" ON public."LiteLLM_TeamTable" USING btree (team_alias);


--
-- Name: LiteLLM_ToolTable_input_policy_idx; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX "LiteLLM_ToolTable_input_policy_idx" ON public."LiteLLM_ToolTable" USING btree (input_policy);


--
-- Name: LiteLLM_ToolTable_output_policy_idx; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX "LiteLLM_ToolTable_output_policy_idx" ON public."LiteLLM_ToolTable" USING btree (output_policy);


--
-- Name: LiteLLM_ToolTable_team_id_idx; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX "LiteLLM_ToolTable_team_id_idx" ON public."LiteLLM_ToolTable" USING btree (team_id);


--
-- Name: LiteLLM_ToolTable_tool_name_key; Type: INDEX; Schema: public; Owner: -
--

CREATE UNIQUE INDEX "LiteLLM_ToolTable_tool_name_key" ON public."LiteLLM_ToolTable" USING btree (tool_name);


--
-- Name: LiteLLM_UserTable_sso_user_id_key; Type: INDEX; Schema: public; Owner: -
--

CREATE UNIQUE INDEX "LiteLLM_UserTable_sso_user_id_key" ON public."LiteLLM_UserTable" USING btree (sso_user_id);


--
-- Name: LiteLLM_UserTable_user_email_lower_idx; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX "LiteLLM_UserTable_user_email_lower_idx" ON public."LiteLLM_UserTable" USING btree (lower(user_email));


--
-- Name: LiteLLM_VerificationToken_budget_reset_at_expires_idx; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX "LiteLLM_VerificationToken_budget_reset_at_expires_idx" ON public."LiteLLM_VerificationToken" USING btree (budget_reset_at, expires);


--
-- Name: LiteLLM_VerificationToken_team_id_idx; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX "LiteLLM_VerificationToken_team_id_idx" ON public."LiteLLM_VerificationToken" USING btree (team_id);


--
-- Name: LiteLLM_VerificationToken_user_id_team_id_idx; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX "LiteLLM_VerificationToken_user_id_team_id_idx" ON public."LiteLLM_VerificationToken" USING btree (user_id, team_id);


--
-- Name: LiteLLM_WorkflowEvent_run_id_idx; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX "LiteLLM_WorkflowEvent_run_id_idx" ON public."LiteLLM_WorkflowEvent" USING btree (run_id);


--
-- Name: LiteLLM_WorkflowEvent_run_id_sequence_number_key; Type: INDEX; Schema: public; Owner: -
--

CREATE UNIQUE INDEX "LiteLLM_WorkflowEvent_run_id_sequence_number_key" ON public."LiteLLM_WorkflowEvent" USING btree (run_id, sequence_number);


--
-- Name: LiteLLM_WorkflowMessage_run_id_idx; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX "LiteLLM_WorkflowMessage_run_id_idx" ON public."LiteLLM_WorkflowMessage" USING btree (run_id);


--
-- Name: LiteLLM_WorkflowMessage_run_id_sequence_number_key; Type: INDEX; Schema: public; Owner: -
--

CREATE UNIQUE INDEX "LiteLLM_WorkflowMessage_run_id_sequence_number_key" ON public."LiteLLM_WorkflowMessage" USING btree (run_id, sequence_number);


--
-- Name: LiteLLM_WorkflowRun_created_at_idx; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX "LiteLLM_WorkflowRun_created_at_idx" ON public."LiteLLM_WorkflowRun" USING btree (created_at);


--
-- Name: LiteLLM_WorkflowRun_created_by_idx; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX "LiteLLM_WorkflowRun_created_by_idx" ON public."LiteLLM_WorkflowRun" USING btree (created_by);


--
-- Name: LiteLLM_WorkflowRun_session_id_idx; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX "LiteLLM_WorkflowRun_session_id_idx" ON public."LiteLLM_WorkflowRun" USING btree (session_id);


--
-- Name: LiteLLM_WorkflowRun_session_id_key; Type: INDEX; Schema: public; Owner: -
--

CREATE UNIQUE INDEX "LiteLLM_WorkflowRun_session_id_key" ON public."LiteLLM_WorkflowRun" USING btree (session_id);


--
-- Name: LiteLLM_WorkflowRun_workflow_type_status_idx; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX "LiteLLM_WorkflowRun_workflow_type_status_idx" ON public."LiteLLM_WorkflowRun" USING btree (workflow_type, status);


--
-- Name: credential_inventory_cool_down_until_idx; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX credential_inventory_cool_down_until_idx ON public.credential_inventory USING btree (cool_down_until) WHERE (cool_down_until IS NOT NULL);


--
-- Name: credential_inventory_provider_status_idx; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX credential_inventory_provider_status_idx ON public.credential_inventory USING btree (provider, status);


--
-- Name: idx_adaptive_router_session_activity; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_adaptive_router_session_activity ON public."LiteLLM_AdaptiveRouterSession" USING btree (last_activity_at);


--
-- Name: credential_inventory credential_inventory_set_updated_at; Type: TRIGGER; Schema: public; Owner: -
--

CREATE TRIGGER credential_inventory_set_updated_at BEFORE UPDATE ON public.credential_inventory FOR EACH ROW EXECUTE FUNCTION public.set_credential_inventory_updated_at();


--
-- Name: LiteLLM_AgentsTable LiteLLM_AgentsTable_object_permission_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public."LiteLLM_AgentsTable"
    ADD CONSTRAINT "LiteLLM_AgentsTable_object_permission_id_fkey" FOREIGN KEY (object_permission_id) REFERENCES public."LiteLLM_ObjectPermissionTable"(object_permission_id) ON UPDATE CASCADE ON DELETE SET NULL;


--
-- Name: LiteLLM_EndUserTable LiteLLM_EndUserTable_budget_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public."LiteLLM_EndUserTable"
    ADD CONSTRAINT "LiteLLM_EndUserTable_budget_id_fkey" FOREIGN KEY (budget_id) REFERENCES public."LiteLLM_BudgetTable"(budget_id) ON UPDATE CASCADE ON DELETE SET NULL;


--
-- Name: LiteLLM_EndUserTable LiteLLM_EndUserTable_object_permission_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public."LiteLLM_EndUserTable"
    ADD CONSTRAINT "LiteLLM_EndUserTable_object_permission_id_fkey" FOREIGN KEY (object_permission_id) REFERENCES public."LiteLLM_ObjectPermissionTable"(object_permission_id) ON UPDATE CASCADE ON DELETE SET NULL;


--
-- Name: LiteLLM_InvitationLink LiteLLM_InvitationLink_created_by_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public."LiteLLM_InvitationLink"
    ADD CONSTRAINT "LiteLLM_InvitationLink_created_by_fkey" FOREIGN KEY (created_by) REFERENCES public."LiteLLM_UserTable"(user_id) ON UPDATE CASCADE ON DELETE RESTRICT;


--
-- Name: LiteLLM_InvitationLink LiteLLM_InvitationLink_updated_by_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public."LiteLLM_InvitationLink"
    ADD CONSTRAINT "LiteLLM_InvitationLink_updated_by_fkey" FOREIGN KEY (updated_by) REFERENCES public."LiteLLM_UserTable"(user_id) ON UPDATE CASCADE ON DELETE RESTRICT;


--
-- Name: LiteLLM_InvitationLink LiteLLM_InvitationLink_user_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public."LiteLLM_InvitationLink"
    ADD CONSTRAINT "LiteLLM_InvitationLink_user_id_fkey" FOREIGN KEY (user_id) REFERENCES public."LiteLLM_UserTable"(user_id) ON UPDATE CASCADE ON DELETE RESTRICT;


--
-- Name: LiteLLM_JWTKeyMapping LiteLLM_JWTKeyMapping_token_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public."LiteLLM_JWTKeyMapping"
    ADD CONSTRAINT "LiteLLM_JWTKeyMapping_token_fkey" FOREIGN KEY (token) REFERENCES public."LiteLLM_VerificationToken"(token) ON UPDATE CASCADE ON DELETE RESTRICT;


--
-- Name: LiteLLM_OrganizationMembership LiteLLM_OrganizationMembership_budget_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public."LiteLLM_OrganizationMembership"
    ADD CONSTRAINT "LiteLLM_OrganizationMembership_budget_id_fkey" FOREIGN KEY (budget_id) REFERENCES public."LiteLLM_BudgetTable"(budget_id) ON UPDATE CASCADE ON DELETE SET NULL;


--
-- Name: LiteLLM_OrganizationMembership LiteLLM_OrganizationMembership_organization_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public."LiteLLM_OrganizationMembership"
    ADD CONSTRAINT "LiteLLM_OrganizationMembership_organization_id_fkey" FOREIGN KEY (organization_id) REFERENCES public."LiteLLM_OrganizationTable"(organization_id) ON UPDATE CASCADE ON DELETE RESTRICT;


--
-- Name: LiteLLM_OrganizationMembership LiteLLM_OrganizationMembership_user_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public."LiteLLM_OrganizationMembership"
    ADD CONSTRAINT "LiteLLM_OrganizationMembership_user_id_fkey" FOREIGN KEY (user_id) REFERENCES public."LiteLLM_UserTable"(user_id) ON UPDATE CASCADE ON DELETE RESTRICT;


--
-- Name: LiteLLM_OrganizationTable LiteLLM_OrganizationTable_budget_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public."LiteLLM_OrganizationTable"
    ADD CONSTRAINT "LiteLLM_OrganizationTable_budget_id_fkey" FOREIGN KEY (budget_id) REFERENCES public."LiteLLM_BudgetTable"(budget_id) ON UPDATE CASCADE ON DELETE RESTRICT;


--
-- Name: LiteLLM_OrganizationTable LiteLLM_OrganizationTable_object_permission_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public."LiteLLM_OrganizationTable"
    ADD CONSTRAINT "LiteLLM_OrganizationTable_object_permission_id_fkey" FOREIGN KEY (object_permission_id) REFERENCES public."LiteLLM_ObjectPermissionTable"(object_permission_id) ON UPDATE CASCADE ON DELETE SET NULL;


--
-- Name: LiteLLM_ProjectTable LiteLLM_ProjectTable_budget_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public."LiteLLM_ProjectTable"
    ADD CONSTRAINT "LiteLLM_ProjectTable_budget_id_fkey" FOREIGN KEY (budget_id) REFERENCES public."LiteLLM_BudgetTable"(budget_id) ON UPDATE CASCADE ON DELETE SET NULL;


--
-- Name: LiteLLM_ProjectTable LiteLLM_ProjectTable_object_permission_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public."LiteLLM_ProjectTable"
    ADD CONSTRAINT "LiteLLM_ProjectTable_object_permission_id_fkey" FOREIGN KEY (object_permission_id) REFERENCES public."LiteLLM_ObjectPermissionTable"(object_permission_id) ON UPDATE CASCADE ON DELETE SET NULL;


--
-- Name: LiteLLM_ProjectTable LiteLLM_ProjectTable_team_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public."LiteLLM_ProjectTable"
    ADD CONSTRAINT "LiteLLM_ProjectTable_team_id_fkey" FOREIGN KEY (team_id) REFERENCES public."LiteLLM_TeamTable"(team_id) ON UPDATE CASCADE ON DELETE SET NULL;


--
-- Name: LiteLLM_TagTable LiteLLM_TagTable_budget_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public."LiteLLM_TagTable"
    ADD CONSTRAINT "LiteLLM_TagTable_budget_id_fkey" FOREIGN KEY (budget_id) REFERENCES public."LiteLLM_BudgetTable"(budget_id) ON UPDATE CASCADE ON DELETE SET NULL;


--
-- Name: LiteLLM_TeamMembership LiteLLM_TeamMembership_budget_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public."LiteLLM_TeamMembership"
    ADD CONSTRAINT "LiteLLM_TeamMembership_budget_id_fkey" FOREIGN KEY (budget_id) REFERENCES public."LiteLLM_BudgetTable"(budget_id) ON UPDATE CASCADE ON DELETE SET NULL;


--
-- Name: LiteLLM_TeamTable LiteLLM_TeamTable_model_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public."LiteLLM_TeamTable"
    ADD CONSTRAINT "LiteLLM_TeamTable_model_id_fkey" FOREIGN KEY (model_id) REFERENCES public."LiteLLM_ModelTable"(id) ON UPDATE CASCADE ON DELETE SET NULL;


--
-- Name: LiteLLM_TeamTable LiteLLM_TeamTable_object_permission_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public."LiteLLM_TeamTable"
    ADD CONSTRAINT "LiteLLM_TeamTable_object_permission_id_fkey" FOREIGN KEY (object_permission_id) REFERENCES public."LiteLLM_ObjectPermissionTable"(object_permission_id) ON UPDATE CASCADE ON DELETE SET NULL;


--
-- Name: LiteLLM_TeamTable LiteLLM_TeamTable_organization_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public."LiteLLM_TeamTable"
    ADD CONSTRAINT "LiteLLM_TeamTable_organization_id_fkey" FOREIGN KEY (organization_id) REFERENCES public."LiteLLM_OrganizationTable"(organization_id) ON UPDATE CASCADE ON DELETE SET NULL;


--
-- Name: LiteLLM_UserTable LiteLLM_UserTable_object_permission_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public."LiteLLM_UserTable"
    ADD CONSTRAINT "LiteLLM_UserTable_object_permission_id_fkey" FOREIGN KEY (object_permission_id) REFERENCES public."LiteLLM_ObjectPermissionTable"(object_permission_id) ON UPDATE CASCADE ON DELETE SET NULL;


--
-- Name: LiteLLM_UserTable LiteLLM_UserTable_organization_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public."LiteLLM_UserTable"
    ADD CONSTRAINT "LiteLLM_UserTable_organization_id_fkey" FOREIGN KEY (organization_id) REFERENCES public."LiteLLM_OrganizationTable"(organization_id) ON UPDATE CASCADE ON DELETE SET NULL;


--
-- Name: LiteLLM_VerificationToken LiteLLM_VerificationToken_budget_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public."LiteLLM_VerificationToken"
    ADD CONSTRAINT "LiteLLM_VerificationToken_budget_id_fkey" FOREIGN KEY (budget_id) REFERENCES public."LiteLLM_BudgetTable"(budget_id) ON UPDATE CASCADE ON DELETE SET NULL;


--
-- Name: LiteLLM_VerificationToken LiteLLM_VerificationToken_object_permission_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public."LiteLLM_VerificationToken"
    ADD CONSTRAINT "LiteLLM_VerificationToken_object_permission_id_fkey" FOREIGN KEY (object_permission_id) REFERENCES public."LiteLLM_ObjectPermissionTable"(object_permission_id) ON UPDATE CASCADE ON DELETE SET NULL;


--
-- Name: LiteLLM_VerificationToken LiteLLM_VerificationToken_organization_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public."LiteLLM_VerificationToken"
    ADD CONSTRAINT "LiteLLM_VerificationToken_organization_id_fkey" FOREIGN KEY (organization_id) REFERENCES public."LiteLLM_OrganizationTable"(organization_id) ON UPDATE CASCADE ON DELETE SET NULL;


--
-- Name: LiteLLM_VerificationToken LiteLLM_VerificationToken_project_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public."LiteLLM_VerificationToken"
    ADD CONSTRAINT "LiteLLM_VerificationToken_project_id_fkey" FOREIGN KEY (project_id) REFERENCES public."LiteLLM_ProjectTable"(project_id) ON UPDATE CASCADE ON DELETE SET NULL;


--
-- Name: LiteLLM_WorkflowEvent LiteLLM_WorkflowEvent_run_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public."LiteLLM_WorkflowEvent"
    ADD CONSTRAINT "LiteLLM_WorkflowEvent_run_id_fkey" FOREIGN KEY (run_id) REFERENCES public."LiteLLM_WorkflowRun"(run_id) ON UPDATE CASCADE ON DELETE RESTRICT;


--
-- Name: LiteLLM_WorkflowMessage LiteLLM_WorkflowMessage_run_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public."LiteLLM_WorkflowMessage"
    ADD CONSTRAINT "LiteLLM_WorkflowMessage_run_id_fkey" FOREIGN KEY (run_id) REFERENCES public."LiteLLM_WorkflowRun"(run_id) ON UPDATE CASCADE ON DELETE RESTRICT;


--
-- PostgreSQL database dump complete
--

\unrestrict k2utT3RLep2AD57pla1t0aR4E7LUFgQyWnpZ6hatE9f7ajOMPtprIPdMdK0Ch1A


-- _prisma_migrations rows so LITELLM_MIGRATIONS=None skips proxy_extras
--
-- PostgreSQL database dump
--

\restrict 5yElRueMjx06XOnondWLNzq64BEYxmU9eE4JsHNq8bYWDXCQRRMNj7zYcW5svVe

-- Dumped from database version 17.10 (Debian 17.10-1.pgdg13+1)
-- Dumped by pg_dump version 17.10 (Debian 17.10-1.pgdg13+1)

SET statement_timeout = 0;
SET lock_timeout = 0;
SET idle_in_transaction_session_timeout = 0;
SET transaction_timeout = 0;
SET client_encoding = 'UTF8';
SET standard_conforming_strings = on;
SELECT pg_catalog.set_config('search_path', '', false);
SET check_function_bodies = false;
SET xmloption = content;
SET client_min_messages = warning;
SET row_security = off;

--
-- Data for Name: _prisma_migrations; Type: TABLE DATA; Schema: public; Owner: -
--

COPY public._prisma_migrations (id, checksum, finished_at, migration_name, logs, rolled_back_at, started_at, applied_steps_count) FROM stdin;
5c16f9ed-3453-4630-bacb-0e8774feae55	1cb236b5c18b69b62b58e8c92cb762cb0be309cfdf2bfd935733ba198673d726	2026-05-19 18:40:31.785114+00	20250425182129_add_session_id	\N	\N	2026-05-19 18:40:31.783285+00	1
7ba9175c-3b82-4aaa-8061-59d802adcdb1	35afca4826335f8bd2bc2b733c0540de51c6a199d39c27a2d1910c53e1a02647	2026-05-19 18:40:31.738648+00	20250326162113_baseline	\N	\N	2026-05-19 18:40:31.699646+00	1
a8aa4e3e-b365-471d-b808-512f3f3da1fe	48b046b5dcfe063869b28fd4c47ed4aa553707ccb02a42be276c43ae0d7cd612	2026-05-19 18:40:31.745713+00	20250326171002_add_daily_user_table	\N	\N	2026-05-19 18:40:31.74018+00	1
21ed7b6e-64f2-493c-87da-538ea579a024	67fdce0f3f25d350bc661f8f32b747ee7cd3e18dab46a90f72ef7e46024098af	2026-05-19 18:40:31.823516+00	20250514142245_add_guardrails_table	\N	\N	2026-05-19 18:40:31.821191+00	1
6c8702c3-2589-4c2d-9e38-5a1d9f370d11	47ffc522eec4af95fc48c18d4f92b86a6dd6c755b2afb40dc4585b69ebd109da	2026-05-19 18:40:31.749089+00	20250327180120_add_api_requests_to_daily_user_table	\N	\N	2026-05-19 18:40:31.74681+00	1
ad02c1d6-2be6-475c-a7c5-8718265cad9b	d89c388b45a1367f0ad93543e56bfeaa32a391ff8adf1c18ab74003635446261	2026-05-19 18:40:31.788829+00	20250430193429_add_managed_vector_stores	\N	\N	2026-05-19 18:40:31.786159+00	1
0461815b-0165-4a9b-a638-297d4f4f6ba3	050f9d2bf329e99b1c294a5c137d73859dded58324af55696d5c7f51f7e281d4	2026-05-19 18:40:31.754219+00	20250329084805_new_cron_job_table	\N	\N	2026-05-19 18:40:31.750274+00	1
adffc94a-1374-4b28-92c6-1bbabdc559f9	049767abdd55f43520a1c2201a9a99f7356be451bec8c7e52895301fa0e2eb61	2026-05-19 18:40:31.756854+00	20250331215456_track_success_and_failed_requests_daily_agg_table	\N	\N	2026-05-19 18:40:31.754923+00	1
a29274a8-59b4-4f24-9501-720169d2f6c5	477ee9e678d0a6f4a3e97898b085a0dfb6ddd24730c28f46e68a700f37ee2d2f	2026-05-19 18:40:31.761068+00	20250411215431_add_managed_file_table	\N	\N	2026-05-19 18:40:31.758033+00	1
75364ff6-0a0d-4e2f-9182-6cd4a31a7dcf	f03c48cd15a994d4e6727cf4749ad27d52277da0d76561e9d7f50de94e8379b0	2026-05-19 18:40:31.7925+00	20250507161526_add_mcp_table_to_db	\N	\N	2026-05-19 18:40:31.789875+00	1
1f70de65-ac4f-4dc4-8625-e3b4ab4c6dac	67b629914bbb8f6fa26c52fac9fd4940a96e5c1371d76dbadc620de66a554244	2026-05-19 18:40:31.76333+00	20250412081753_team_member_permissions	\N	\N	2026-05-19 18:40:31.761786+00	1
f34e51d0-7886-425e-ba17-1547cb36a55b	bc904bdd0befbb6e2fb96b6f4bb7699d1c85518b85cce7f1822524d64d67c3ff	2026-05-19 18:40:31.76564+00	20250415151647_add_cache_read_write_tokens_daily_spend_transactions	\N	\N	2026-05-19 18:40:31.764011+00	1
06a363e6-0574-4929-a231-02a1b1dc859c	bf163aaf3bcb043f81cdaba361207009399bc74e64417b30289f241206fd5dfd	2026-05-19 18:40:31.862664+00	20250802162330_prompt_table	\N	\N	2026-05-19 18:40:31.860568+00	1
2f1038c0-ef54-4063-8622-30dc37a590d5	f07d74cf601a93592bf6fb0cd732d21a261a23c461b4d64a5eb500b82f38e1c8	2026-05-19 18:40:31.770374+00	20250415191926_add_daily_team_table	\N	\N	2026-05-19 18:40:31.766309+00	1
31d00f00-a28d-4121-9c50-5d6d9d4547e5	b0cb512a90b674c5531b2c722048c936efefe834b3050715483d1b9c3c195de2	2026-05-19 18:40:31.79527+00	20250507161527_add_health_check_fields_to_mcp_servers	\N	\N	2026-05-19 18:40:31.79348+00	1
8dc1a5e0-f1dd-4389-ae35-8f740c468b1f	7a4a9a98c40803f33f46ece325a233687df1d69402e7536b5e0ae3fb7cdb94d8	2026-05-19 18:40:31.776048+00	20250416115320_add_tag_table_to_db	\N	\N	2026-05-19 18:40:31.771062+00	1
938d5663-0089-4d16-9951-68099d1b3022	e795d3fc96efff0b386425d5d1090319280317dd5954a01614f828a6e020302a	2026-05-19 18:40:31.779468+00	20250416151339_drop_tag_uniqueness_requirement	\N	\N	2026-05-19 18:40:31.77711+00	1
3a3fdd33-45e1-4c7b-97c6-e9886b5aeae1	9f4099edfb29658b8330afec322d97f2f1233fae81946c51521bbdcde5bf67e0	2026-05-19 18:40:31.827428+00	20250522223020_managed_object_table	\N	\N	2026-05-19 18:40:31.824231+00	1
a59296b9-1b1f-42a2-b185-8d10256af3bc	35377cad4aaf835bd319f56811c344d53654ea664216f39c15ddd20434c1b69c	2026-05-19 18:40:31.782277+00	20250416185146_add_allowed_routes_litellm_verification_token	\N	\N	2026-05-19 18:40:31.780358+00	1
678274c0-ae23-49b1-849a-1bb60d5c3925	3fc693f5dbdbb9968a6d95f2c940a04646b258eb671c70ff01bf4772e27e5979	2026-05-19 18:40:31.80153+00	20250507184818_add_mcp_key_team_permission_mgmt	\N	\N	2026-05-19 18:40:31.796343+00	1
d02657a8-68f5-4818-be6c-0f10e4da3ab6	4ae034e93702511a6641b53102836f239cfee44393703b4ac0be0a5849f69bde	2026-05-19 18:40:31.844694+00	20250625145206_cascade_budget_and_loosen_managed_file_json	\N	\N	2026-05-19 18:40:31.842208+00	1
0cc5fecf-d68c-41e8-b0fc-d85d77eff4c3	ad1052154ae85e7a3beac99764f23ee50feb0eb745a0970935a471d5e730f433	2026-05-19 18:40:31.804407+00	20250508072103_add_status_to_spendlogs	\N	\N	2026-05-19 18:40:31.802539+00	1
0ffddaa7-f1aa-4704-af3c-847e692c4aa3	3bd0b7fd731a1d2e43aaefc346dca6f3d6e1b29022792422429c4ad4c4d06604	2026-05-19 18:40:31.830483+00	20250526154401_allow_null_entity_id	\N	\N	2026-05-19 18:40:31.828491+00	1
6a7d20e6-cd7b-4e2f-b1dd-630489e28630	50f6805ecaf21af5594ff4a739ffb5c87bb96ca3d356bda03f7cd8eb814a47ba	2026-05-19 18:40:31.817218+00	20250509141545_use_big_int_for_daily_spend_tables	\N	\N	2026-05-19 18:40:31.805431+00	1
3ccc326c-45a2-4e02-998a-93f4384fc4b9	f718b2a74f2a8529c079242e36330206a17b985d31d36e16fc31861090a74c93	2026-05-19 18:40:31.820417+00	20250510142544_add_session_id_index_spend_logs	\N	\N	2026-05-19 18:40:31.818358+00	1
238f18b0-5baf-4ac8-a044-e25651ff72fe	f345c94a2d1ba5250b8185f86068dc29c8cb1535f13cf5b670dc25f5fb03d2e6	2026-05-19 18:40:31.854622+00	20250707230009_add_mcp_namespaced_tool_name	\N	\N	2026-05-19 18:40:31.850577+00	1
d8e4b457-ce4f-4baa-a49f-ad8a5c39ace4	55939a32735a821668ea76cf37ad550e0f567225eec6d7595221a9f7445e5854	2026-05-19 18:40:31.833321+00	20250528185438_add_vector_stores_to_object_permissions	\N	\N	2026-05-19 18:40:31.831489+00	1
1633ce97-1975-4b85-b6b1-9154fd186910	a397ffbfaba32f88d7d453b28f24e3dc8dc240974926e0456d9eaab06fb34b09	2026-05-19 18:40:31.847213+00	20250625213625_add_status_to_managed_object_table	\N	\N	2026-05-19 18:40:31.845701+00	1
8a233e5b-26f6-4ebd-a3a7-cf0861cd41a4	c2eb9e521552dbb2f7f14652a7f0d66c892589745ef121c1799e06fa5bd53e2d	2026-05-19 18:40:31.836812+00	20250603210143_cascade_budget_changes	\N	\N	2026-05-19 18:40:31.834314+00	1
c214cadd-9f5a-45d3-b48d-7fa298351e4e	9e8723ee10d9ce8c5dcad41da4bcb2f8db2d7cab415eff59eb3ecc38b698d2e9	2026-05-19 18:40:31.841198+00	20250618225828_add_health_check_table	\N	\N	2026-05-19 18:40:31.83792+00	1
e411289e-ad19-4843-9524-fb25f4f9527f	820dbb9d88eba37648b5e65c2beedfaa022276fc5a704a8fddafb5e36dcc9038	2026-05-19 18:40:31.849893+00	20250707212517_add_mcp_info_column_mcp_servers	\N	\N	2026-05-19 18:40:31.848171+00	1
ee2f7144-fc8a-47e2-8ed9-85e6773bb0b5	11655e562e501337d5b19c56e7d2785f9f3964c16d0bda4f701f9c26c4bedc8e	2026-05-19 18:40:31.859926+00	20250718125714_add_litellm_params_to_vector_stores	\N	\N	2026-05-19 18:40:31.858639+00	1
1c6ab94a-3aed-47b3-891c-4df6a4d85ed9	b1d0f71ed415833ebf31efbad070bc73e2fafce59ec148d3087071848d5282b9	2026-05-19 18:40:31.857628+00	20250711220620_add_stdio_mcp	\N	\N	2026-05-19 18:40:31.855719+00	1
03dadf02-e42b-40b4-a45d-1386b0255a62	0607b76d63bdea31615737631d7e6c0fb4b308b9ebad832affa8a5cc914043ac	2026-05-19 18:40:31.869858+00	20250806095134_rename_alias_to_server_name_mcp_table	\N	\N	2026-05-19 18:40:31.863333+00	1
284da34c-9c74-4ff4-979e-33fa33b8dc26	9bda666c0d3ce21746477a5a28c2b35a715579e9c55460c50dbc334d790aff1b	2026-05-19 18:40:31.872662+00	20250918083359_drop_spec_version_column_from_mcp_table	\N	\N	2026-05-19 18:40:31.870804+00	1
c716b3e1-0fac-4b4c-a412-6bae8fa35e23	425b6e795967c9f494c5a2d612d0d0d3203d263b843727941ce3a262064c398a	2026-05-19 18:40:31.875494+00	20250926194702_unnamed_migration	\N	\N	2026-05-19 18:40:31.873597+00	1
9527bc3f-bd5f-4e8e-b0f6-e04956e71e05	4f9c1595a2d6bddf693ec845058f9413aeffc8a6ea8b46b53566a36b6d93f1e2	2026-05-19 18:40:31.878111+00	20251003165142_add_allowed_tools_to_mcp	\N	\N	2026-05-19 18:40:31.876462+00	1
082ebbce-4782-4af1-86b2-04ad505ab018	fe1ae32b28502546173d9345e4d55d05f9644f87750ba9e0a1b28c35c9291f51	2026-05-19 18:40:31.881454+00	20251003190954_extra_headers_to_mcp_table	\N	\N	2026-05-19 18:40:31.879191+00	1
e706c757-ef21-41c8-b81f-514ef9b24e94	547773d84d26f9f215bd7d2674ed404811e541358755220bb716c0b97c81fe86	2026-05-19 18:40:31.991827+00	20260131150814_add_team_user_to_vector_stores	\N	\N	2026-05-19 18:40:31.98978+00	1
d75418cf-10c3-404c-9566-166859994c17	6562a695c0bc052bfbb76da2ee4db808d6070e0c9e421d54ddf69bf943ec922d	2026-05-19 18:40:31.884065+00	20251006143948_add_mcp_tool_permissions	\N	\N	2026-05-19 18:40:31.882437+00	1
89138eb8-4788-4236-8b2f-4c99727ce8bf	d2723db3432cddfb6f6e0cf85b14297fe0e2157fc4b8dd1e2f7819a740cccc36	2026-05-19 18:40:31.933251+00	20251122125322_Add organization_id to spend logs	\N	\N	2026-05-19 18:40:31.931641+00	1
12aee924-a006-4665-9f2b-7984f20fd6a8	aa1d44f4a4762cb046d6c1103fcbcb9bd43625188e864d76da236190289194b4	2026-05-19 18:40:31.888766+00	20251011084309_add_tag_table	\N	\N	2026-05-19 18:40:31.885069+00	1
a46fbb9d-cadf-4c86-bcd0-7d811459c12f	663483c4470c0ede72f80da33da2361d94bba8700387d748960dc20ea7785ccb	2026-05-19 18:40:31.893229+00	20251023141814_add_search_tool_table	\N	\N	2026-05-19 18:40:31.889835+00	1
2a6b6f7d-dd3c-4fc3-8eae-cf9396825f5e	8e219b15b4e476b22c1716992fd513152039de1c5951a0ac694d1ffba26111b3	2026-05-19 18:40:31.963809+00	20251220144550_schema_update	\N	\N	2026-05-19 18:40:31.96145+00	1
11467879-8636-486d-bea1-1e588a0337e8	2f4cd52ea467195bd838bd8fc9df0ae1c443db0fe4985fa1a83a7032f9b36018	2026-05-19 18:40:31.897636+00	20251031181430_add_cache_config_table	\N	\N	2026-05-19 18:40:31.89419+00	1
358fdd6a-3b72-4b58-8a6d-bf9c6c24a449	bc1914aefc7203fdcaadb7b70ae513b2e75bd72b268f5fde8e144caabb3a1b45	2026-05-19 18:40:31.937889+00	20251204124859_add_end_user_spend_table	\N	\N	2026-05-19 18:40:31.933985+00	1
ff8cfbb8-fc70-46de-9945-a6c5c95490da	95564113904a3f141e4470aa3dfc1f559e3d23a8a3f64e9986833d725ea83b28	2026-05-19 18:40:31.901466+00	20251101131415_add_managed_vector_store_index_table	\N	\N	2026-05-19 18:40:31.898637+00	1
2b2e6472-ae9c-4187-810a-a267510e2254	5a06bdfc76f654b56cb4b6e6f7a8cbc8710d8bf8a956fbec315befa047c0851d	2026-05-19 18:40:31.904295+00	20251103072422_add_static_headers	\N	\N	2026-05-19 18:40:31.902456+00	1
0d4ccf3f-a822-4b97-bb0a-1bf49da530b8	d41ba79c0256b803302c6af066885c779a1b1ce5d697347fa8853871d851fc65	2026-05-19 18:40:31.907022+00	20251104220043_add_credentials_to_mcp_servers	\N	\N	2026-05-19 18:40:31.905256+00	1
8a993e12-fd93-4b67-8a9b-aac5a63e8c96	86038393c8ebaf7bb60df05dfa7024a17fe8c03aa7fac858beaaf8f07ec753bc	2026-05-19 18:40:31.940328+00	20251204142718_add_agent_permissions	\N	\N	2026-05-19 18:40:31.93864+00	1
7aa5c3f2-ac69-4d85-bd7d-45cd0eaca9d7	f9ca207f007c9d80c433f918d6d432598614df5dc89ec7fc8d9effe5ebf23744	2026-05-19 18:40:31.913467+00	20251113000000_add_project_table	\N	\N	2026-05-19 18:40:31.908443+00	1
6cd12b7f-5797-4238-a28c-0c6d51f7f0a5	bb9657c76de699e4527516929492dbb173c2d800b242a5db30c1ff803f56a0b1	2026-05-19 18:40:31.916285+00	20251113000001_add_project_fields	\N	\N	2026-05-19 18:40:31.91448+00	1
7e6bd7bb-b5dc-4e25-b263-fdbfd0ddfc86	3cb5404a0f325ccf199bb63b283e4da752d97c5012c736cb9cd00755f8ebae03	2026-05-19 18:40:31.980744+00	20260108_add_user_email_lower_idx	\N	\N	2026-05-19 18:40:31.97876+00	1
6e5282de-14d5-41d3-a139-b16013f00731	756a19475ebee069e8847fa65f3210ba7bb5b816929a477588c67dfa8adf743f	2026-05-19 18:40:31.918771+00	20251114173537_add_request_id_to_daily_tag_spend	\N	\N	2026-05-19 18:40:31.917263+00	1
eddfd24e-a064-4f07-a42a-95e25f2f8e45	3ad6c3f157817a4b3d37832d0e0cb78455a50466315c20e6462f07ccd166f882	2026-05-19 18:40:31.943355+00	20251209112246_add_ui_settings_table	\N	\N	2026-05-19 18:40:31.941034+00	1
8c70902b-48a7-4150-870d-723ce00bd35b	83ba27846dec4011f8b17df50b47cfb9200f6198c5398a47bf2c0be32fffd430	2026-05-19 18:40:31.92395+00	20251114180624_Add_org_usage_table	\N	\N	2026-05-19 18:40:31.919831+00	1
079eaeda-0653-4076-8abd-241c38233373	04abaf00e118987d0a9de36954f2fddc97c456e4af4f0e203b5141427743f33c	2026-05-19 18:40:31.927721+00	20251114182247_agents_table	\N	\N	2026-05-19 18:40:31.925124+00	1
87629e7e-0117-4f5e-bf2a-9542d62ecadf	eee02bb2a33b6bdf324081d9006f8da5f1298a0c7f8fa4ae52391d4b3fdd2d2e	2026-05-19 18:40:31.965987+00	20260102131258_add_metadata_urls_to_mcp_servers	\N	\N	2026-05-19 18:40:31.964487+00	1
f8869b1f-8478-4697-9228-4e50014ea593	9796ddf9bc6994b507ff9f6a9e460a284230ab3f4dde4cd1a9224f21f08e19c5	2026-05-19 18:40:31.930591+00	20251119131227_add_prompt_versioning	\N	\N	2026-05-19 18:40:31.928428+00	1
93833ffb-8b52-4a4d-979b-7d5d4a7a4c69	2b23aa2aee91f35133eb0e38e413c5979df9ff9949d57ac70550a5a17ad1a53f	2026-05-19 18:40:31.946332+00	20251210125210_add_storage_backend_to_managed_files	\N	\N	2026-05-19 18:40:31.944363+00	1
6f2b5086-1ba8-46a7-b526-aec1037e4ad1	43177e6394f79b21baa869588551f62b41349536239891113d3016eae7552353	2026-05-19 18:40:31.951404+00	20251210205007_add_daily_agent_spend_table	\N	\N	2026-05-19 18:40:31.947416+00	1
8754fa96-a6a5-457c-ba2e-ee3960286168	375bcf8045e6cacdaeeca5e120516aa9bd57743e926f48cad66dbaeb09f6ad57	2026-05-19 18:40:31.95322+00	20251211100212_schema_sync	\N	\N	2026-05-19 18:40:31.95208+00	1
7aceec08-131e-4dca-af74-7fa2a57afd99	b28ffa7014e196d4b1a8e7d52371be91d5633a6b661f0e5e6346b3fc18fd6456	2026-05-19 18:40:31.968511+00	20260105151539_add_allow_all_keys_to_mcp_servers	\N	\N	2026-05-19 18:40:31.967053+00	1
0dec2140-ba34-434a-8c11-d9f524b01fa3	3b3de59c965b5fec61886f09fa0c3e406c1d1194b8674353ea4b7baac3cba3af	2026-05-19 18:40:31.960763+00	20251219110931_add_deleted_keys_and_deleted_teams_tables	\N	\N	2026-05-19 18:40:31.953993+00	1
8df9771a-27aa-4bf1-b585-f46c0a535367	ccfeb894b1fab623593531f189dcd0c098352f9c65c407cb70d2ea9a6086a656	2026-05-19 18:40:31.975299+00	20260106155622_add_endpoint_to_daily_activity_tables	\N	\N	2026-05-19 18:40:31.969274+00	1
6b22b842-c38f-4044-bbf6-2a7f4c1b0fd2	b73e82dcb5dd5607c3635a651f7fbc7d7b9d943504e28e4ae58384d3c970706f	2026-05-19 18:40:31.983681+00	20260116142756_update_deleted_keys_teams_table_routing_settings	\N	\N	2026-05-19 18:40:31.981774+00	1
d333e69f-6faa-4cd7-b009-646886b9d878	9aebf31dd752cf36c8f084d00053ff83af52bf45845549cbb9cb901147d8f2d5	2026-05-19 18:40:31.977716+00	20260107111013_add_router_settings_to_keys_teams	\N	\N	2026-05-19 18:40:31.975986+00	1
8bd77eaa-8c1a-4da7-baae-076a9f50a87e	1d364b454c528c4662780cc4a0ddb12f4c18e82b5eebc83a72fd4429ff367aa1	2026-05-19 18:40:31.998027+00	20260205091235_allow_team_guardrail_config	\N	\N	2026-05-19 18:40:31.99649+00	1
163c3d50-e4fb-4a20-b612-0ccb73db5d0e	45714f4a2e87eb33b7ef53a5320235b5cafc8a0cc307b00743e74dae6719ea67	2026-05-19 18:40:31.989062+00	20260123131407_add_policy_tables_and_policies_field	\N	\N	2026-05-19 18:40:31.984739+00	1
2f254ab8-124d-493b-9f16-65fc88b0b1d8	3dc7d10d308db8101ff1b79a92aff63348f3a686736d4bed672c02c8e8ceb3cf	2026-05-19 18:40:31.99575+00	20260203120000_add_deprecated_verification_token_table	\N	\N	2026-05-19 18:40:31.992947+00	1
51396260-91d1-4bb5-a21a-3f4585efd324	bdb5f1a12ad5eb20c962d03bfd05d6aee6fce92cfd50972d61864856753b0e3a	2026-05-19 18:40:32.004059+00	20260207093506_add_available_on_public_internet_to_mcp_servers	\N	\N	2026-05-19 18:40:32.001187+00	1
26b5e16a-30c7-4a3c-9cde-cbfc081a0f4a	f1f3c7982ff5ff7f55b064d247cc39ce39e882c7d02abf621669e1b76e437442	2026-05-19 18:40:32.000162+00	20260205144610_add_soft_budget_to_team_table	\N	\N	2026-05-19 18:40:31.998736+00	1
16e5b49b-877c-49ee-af92-921be34bcb37	f7c32024cf470b46700be73100dc1e08010942989e908ceb12a5b0e72f95fb5f	2026-05-19 18:40:32.006469+00	20260207110613_add_soft_budget_to_deleted_teams_table	\N	\N	2026-05-19 18:40:32.005082+00	1
6d1f2fbc-1c01-42b0-a431-99a5e253aa76	3cea96b5d541ed36ab8bd027ea3a05094ee235ae9867228aa2fb04c3723fb324	2026-05-19 18:40:32.009166+00	20260209085821_add_verificationtoken_indexes	\N	\N	2026-05-19 18:40:32.007178+00	1
4c3fbe72-2f91-49b7-8c70-a05e7bf7a74c	a782f25b1d9fef4048b24e768f076cabee428060151761cbb9331efa78686ee7	2026-05-19 18:40:32.011685+00	20260212103349_adjust_tags_policy_table	\N	\N	2026-05-19 18:40:32.010055+00	1
d30bb20c-6eb0-42d5-ad13-b7dcda9ce6d6	c245f807fcfd72bf80d438f1459fa60c9d4fb445990b154b5ed1bb0fa9ba1872	2026-05-19 18:40:32.016501+00	20260212143306_add_access_group_table	\N	\N	2026-05-19 18:40:32.012749+00	1
1ca5a0b2-998a-4263-8b17-b915ee854dca	70826378aec43d18575c23e83417bc11455a267104eb0909918a96a24118ba55	2026-05-19 18:40:32.060326+00	20260222000000_add_batch_processed_to_managed_object_table	\N	\N	2026-05-19 18:40:32.058823+00	1
b527b83d-492d-4387-ab7c-d65b41a49d54	5ac7e8b6bfb25f1a6d931d545e32929108c76612e73eae2e806ea18058d42ecc	2026-05-19 18:40:32.020984+00	20260213105436_add_managed_vector_store_table	\N	\N	2026-05-19 18:40:32.017576+00	1
21544c46-1aad-4c17-acee-150c24f72d48	153e085303ec6c02df5d6fc44a152a853a33b498a252b3c8b1c48056a8da231a	2026-05-19 18:40:32.023723+00	20260213170952_access_group_change_to_model_name	\N	\N	2026-05-19 18:40:32.021979+00	1
b946437b-3ad0-4fb9-bf82-26ffbf5ba32d	e007fdb13fe6128d5ac59ae7e7c4b92b08a147a38a44ddcf518dbe94d3904726	2026-05-19 18:40:32.084152+00	20260228110000_mcp_default_public_internet_true	\N	\N	2026-05-19 18:40:32.082388+00	1
5faf3040-63f2-4887-952c-6dfd8c4a63b3	7269a6d0c0734aced27e3cbcc5841fce76f2f9990b2d44dbcba886f0188e7171	2026-05-19 18:40:32.025711+00	20260214094754_schema_sync	\N	\N	2026-05-19 18:40:32.024404+00	1
af309b54-034a-437d-b889-76f5e8645167	bc0cb6ca3c8f432c0b32ad128fa3667ed991245b672e62e9fd18ca34552482ee	2026-05-19 18:40:32.062404+00	20260224201417_spend_logs_request_duration	\N	\N	2026-05-19 18:40:32.061086+00	1
4a004a74-7375-4319-b54b-dbd7e72192e3	ec5ae74d2da8fcc40a42d7f48b2e4ad951677f4e4988a5d52af3665ad54b5e72	2026-05-19 18:40:32.028251+00	20260214163027_add_pipeline_to_policy_table	\N	\N	2026-05-19 18:40:32.026719+00	1
607b6806-6473-449c-bb0d-0b2182e0cae8	be60adf5a2b5cee92eed4e17e2d213d0a12c1debd55a637e7ba05e3a234bb2b3	2026-05-19 18:40:32.031532+00	20260214185341_object_permissions_for_end_users	\N	\N	2026-05-19 18:40:32.029332+00	1
5c5c1882-ef76-4065-9cd3-16a95008080c	7f63ab0118b1e6582eb284dd957c708ff77efe0463219f895a2dee48f0beb6e3	2026-05-19 18:40:32.034209+00	20260218231534_add_last_active_to_key_table	\N	\N	2026-05-19 18:40:32.032573+00	1
7d266120-8ea2-4e5b-85d9-c333b8a430cf	c7d02b13901092b4f9bcc4eac1102f23ba8d639ed3fa9745277647df904afb92	2026-05-19 18:40:32.067851+00	20260224203854_add_agent_object_permissions_table	\N	\N	2026-05-19 18:40:32.063477+00	1
4119f2b1-8e94-44e0-a536-b2fde90de338	a8a34c4f3f2e5db16ee907152ebf836f5a63aea777798a66069c8af7997869a4	2026-05-19 18:40:32.036905+00	20260219105005_add_project_id_to_deleted_keys	\N	\N	2026-05-19 18:40:32.03519+00	1
c661fcac-cdc1-4af8-b136-1be630344ec3	ecbd073ba23472f98ede77177d4318abb9ae0958bae691ed3939dead91bd299e	2026-05-19 18:40:32.043622+00	20260219181415_baseline_diff	\N	\N	2026-05-19 18:40:32.038034+00	1
2fa00031-87c3-4666-8ea9-07f6c5268151	cbf048fe8db758b349f53a1d4e25107d354a41c3aa9080bb1d5a091343e125b0	2026-05-19 18:40:32.11792+00	20260309000001_add_mcp_source_url	\N	\N	2026-05-19 18:40:32.11617+00	1
877f77fb-9869-4a4a-b38d-db550a5e2810	e49454e7f5be2ba0e46da7e5be61900942398f971dcfb0ab70ff4fcef9cfd50e	2026-05-19 18:40:32.046655+00	20260220124742_add_spec_path_to_mcp_servers	\N	\N	2026-05-19 18:40:32.044609+00	1
d5b256dd-2c4c-4014-8be3-4d81ca6b7d93	855545571013964f192ec7d066c001392d2778c47ad1306c974322cc4ad7482f	2026-05-19 18:40:32.070023+00	20260226000000_add_blocked_tools_to_object_permission	\N	\N	2026-05-19 18:40:32.068605+00	1
6162ba07-1a34-4280-a1eb-7af20e28edb0	3f509af1ecb34b350a56f8e35ef47944541f487ddf5033e70f05c2f0ebcc0615	2026-05-19 18:40:32.051832+00	20260220153844_add_composite_index_aggregate_tables	\N	\N	2026-05-19 18:40:32.047763+00	1
a5c47d47-e618-454c-b725-a5c76906755b	c6e0c6f91022ecb66af31eb3778913a2313b1b8270dd7f241681abf354ce306d	2026-05-19 18:40:32.054478+00	20260221000000_ensure_project_id_verification_token	\N	\N	2026-05-19 18:40:32.052915+00	1
f5965d25-7e3f-4da5-a74d-d114923509fe	3610ed4728cd666030881bc61380441901e65a0705296ed255a1bc5001bf6457	2026-05-19 18:40:32.086866+00	20260228170127_support_team_based_guardrails	\N	\N	2026-05-19 18:40:32.085009+00	1
1879e5e4-b620-4120-9c36-25857c3d8c75	7f3f29b50badc248a70f5a4aaee3ed06d933e1ad8ebaef543338a6cb816faf4b	2026-05-19 18:40:32.057727+00	20260221183800_add_policy_versioning	\N	\N	2026-05-19 18:40:32.055206+00	1
4b8642fa-9b00-4ce1-b7d7-c258b43a6b10	019ae3e4e71f35763d6d515e1d463d97e75b8c50e7637c842e4e16ce59009a4b	2026-05-19 18:40:32.072988+00	20260226120000_add_spend_log_tool_index	\N	\N	2026-05-19 18:40:32.07074+00	1
113bca3f-057e-4be7-b19f-e2f39b74f382	f4b1682d40d1999b98215a0677481980372e4cb5659d071e878a343a7a65944b	2026-05-19 18:40:32.103872+00	20260306175056_add_configs_override_table	\N	\N	2026-05-19 18:40:32.102379+00	1
4f6a8380-1518-43e1-8a27-ef4919f6f38f	67af990c525e2160cbda0c759d6992ccbfc4b228313c2439b3b47f93c5c4c13c	2026-05-19 18:40:32.075148+00	20260226202727_add_agent_id_to_delete_keys	\N	\N	2026-05-19 18:40:32.073681+00	1
6efc034c-acdf-43ee-a30f-aa9bfd2809fd	e85f13e8222e6aa682cf1c8e8af45823bf480d85446893c71d77fbea18adcd61	2026-05-19 18:40:32.093406+00	20260303000000_update_tool_table_policies	\N	\N	2026-05-19 18:40:32.087925+00	1
b4742778-a3d2-420b-8a2e-2819ee7f03da	97f41d1817251781594a1dbf5d812f1a860ff21da79d11e914d5151179481fd4	2026-05-19 18:40:32.078833+00	20260228000000_add_claude_code_plugin_table	\N	\N	2026-05-19 18:40:32.076201+00	1
df13c751-66d8-4a00-a927-39e4335b2523	7ece8b0cdb67336e9914f87882bcc804ada60de54a715f10175a9450748d6cfa	2026-05-19 18:40:32.081381+00	20260228100000_add_spend_logs_composite_index	\N	\N	2026-05-19 18:40:32.079557+00	1
fb1b46b2-56ba-46c8-be94-9a4b370f73c6	cbdcbf988896f0ba08bc774f345f550ea3c784c4bc5eda872af093be346cc84d	2026-05-19 18:40:32.096027+00	20260304175016_add_spend_to_agent_table	\N	\N	2026-05-19 18:40:32.094406+00	1
9640310c-6978-4562-af2d-1cde72a02b4c	1fac2f1e9d937b170c06b7828f3de1290d056287d81901b03c174d75bf1e0604	2026-05-19 18:40:32.111354+00	20260306233848_schema_sync	\N	\N	2026-05-19 18:40:32.10468+00	1
6bb2fcd8-f5d3-41b0-87e3-70d500c20230	225bc1c1da92e33d0088e7703fe786430da76cc631317eaef1d4aecc520f8262	2026-05-19 18:40:32.098494+00	20260305000000_add_agent_headers	\N	\N	2026-05-19 18:40:32.096771+00	1
39dc1834-d106-4c16-acbe-1e7466a5ff69	ebe9b00cdbe4225e49f9bba8d0dcf1e22dc7b43f63bb5ccebc8fdde76f227f14	2026-05-19 18:40:32.101404+00	20260305000000_add_rate_limits_to_agents	\N	\N	2026-05-19 18:40:32.09953+00	1
0cd9f6e0-9d0e-45f3-a0ed-cf7b2fea705f	69c77e41e45c3f24f50bfccc2801795aa9ecbdada2cc35263f1977a81457d55a	2026-05-19 18:40:32.115177+00	20260309000000_add_mcp_approval_status	\N	\N	2026-05-19 18:40:32.112563+00	1
584f7f7e-457c-43c8-a7e9-692af09177a2	6d2aa9c28c9c3de83bd5f6cee2bdc6a2b671f348ca8dee58dfc7ffd2abf831cb	2026-05-19 18:40:32.12699+00	20260318140652_add_index_to_team_table	\N	\N	2026-05-19 18:40:32.124678+00	1
c1c6cb35-5428-44ff-9504-1e1b4f866291	f7b2c1b6b2d80e9b787fe29f555f77bbb24add88cc54ea8a766f364319c3a59b	2026-05-19 18:40:32.120903+00	20260311180521_schema_sync	\N	\N	2026-05-19 18:40:32.118727+00	1
a6a48ff6-3b1e-48b0-82df-c55cf96bf75b	62bc045f03c1393c83743262d885693297f891b879bcbf11c749c588e005525b	2026-05-19 18:40:32.123644+00	20260312124619_schema_sync	\N	\N	2026-05-19 18:40:32.121914+00	1
023cc31f-e3de-47aa-81f8-080b1b615f78	e69c9f21be2b53770b13ea52bf6c4f304a9fc86b41f1e932729ec2de45574341	2026-05-28 22:45:56.590926+00	20260527200658_baseline_diff	\N	\N	2026-05-28 22:45:56.587341+00	1
046d16da-2f17-4af1-891e-154d1a9f57b5	e69c9f21be2b53770b13ea52bf6c4f304a9fc86b41f1e932729ec2de45574341	2026-05-31 12:44:55.932287+00	20260529102901_baseline_diff	\N	\N	2026-05-31 12:44:55.929021+00	1
fe265767-cdf9-4e05-b68f-41e9e4cef718	e69c9f21be2b53770b13ea52bf6c4f304a9fc86b41f1e932729ec2de45574341	2026-05-31 12:45:29.168406+00	20260531124457_baseline_diff	\N	\N	2026-05-31 12:45:29.165825+00	1
ece3a81a-9a75-4a31-95b6-bad7cf284bd0	e69c9f21be2b53770b13ea52bf6c4f304a9fc86b41f1e932729ec2de45574341	2026-05-31 13:13:14.813227+00	20260531124530_baseline_diff	\N	\N	2026-05-31 13:13:14.808248+00	1
494fa001-f65a-42d1-86b3-e844285c43e1	e69c9f21be2b53770b13ea52bf6c4f304a9fc86b41f1e932729ec2de45574341	2026-05-31 16:43:58.201212+00	20260531161410_baseline_diff	\N	\N	2026-05-31 16:43:58.198153+00	1
472db635-97a7-4f16-aec2-8eba4fc2ff88	e69c9f21be2b53770b13ea52bf6c4f304a9fc86b41f1e932729ec2de45574341	2026-06-01 20:41:47.490638+00	20260531203956_baseline_diff	\N	\N	2026-06-01 20:41:47.487431+00	1
90cbd24d-fe01-4de3-984e-f751c077448c	8d01e6eec89d0db236ee0861c686e61c60ae0533076671ae8825e9bd92f911a9	\N	20260519184033_baseline_diff	A migration failed to apply. New migrations cannot be applied before the error is recovered from. Read more about how to resolve migration issues in a production database: https://pris.ly/d/migrate-resolve\n\nMigration name: 20260519184033_baseline_diff\n\nDatabase error code: 42701\n\nDatabase error:\nERROR: column "approval_status" of relation "LiteLLM_MCPServerTable" already exists\n\nDbError { severity: "ERROR", parsed_severity: Some(Error), code: SqlState(E42701), message: "column \\"approval_status\\" of relation \\"LiteLLM_MCPServerTable\\" already exists", detail: None, hint: None, position: None, where_: None, schema: None, table: None, column: None, datatype: None, constraint: None, file: Some("tablecmds.c"), line: Some(7478), routine: Some("check_for_column_name_collision") }\n\n   0: sql_schema_connector::apply_migration::apply_script\n           with migration_name="20260519184033_baseline_diff"\n             at schema-engine/connectors/sql-schema-connector/src/apply_migration.rs:106\n   1: schema_core::commands::apply_migrations::Applying migration\n           with migration_name="20260519184033_baseline_diff"\n             at schema-engine/core/src/commands/apply_migrations.rs:91\n   2: schema_core::state::ApplyMigrations\n             at schema-engine/core/src/state.rs:201	2026-05-19 21:49:52.616888+00	2026-05-19 21:49:46.770967+00	0
f9c6b569-4e4d-47db-8149-7d4895cce30d	8d01e6eec89d0db236ee0861c686e61c60ae0533076671ae8825e9bd92f911a9	2026-05-19 21:49:58.456331+00	20260519184033_baseline_diff		\N	2026-05-19 21:49:58.456331+00	0
c953de6b-912d-46a7-b513-a221b4360bc0	e69c9f21be2b53770b13ea52bf6c4f304a9fc86b41f1e932729ec2de45574341	2026-05-19 22:42:15.86747+00	20260519223533_baseline_diff	\N	\N	2026-05-19 22:42:15.863494+00	1
aaf5ec9f-c1c7-4ee3-8aff-695b20de3e82	e69c9f21be2b53770b13ea52bf6c4f304a9fc86b41f1e932729ec2de45574341	2026-05-20 20:57:28.458314+00	20260520205639_baseline_diff	\N	\N	2026-05-20 20:57:28.4547+00	1
f68860a5-5133-4bb0-8a52-fda0a4c21a97	e69c9f21be2b53770b13ea52bf6c4f304a9fc86b41f1e932729ec2de45574341	2026-05-19 22:50:06.743794+00	20260519224217_baseline_diff	\N	\N	2026-05-19 22:50:06.740297+00	1
f32bc6a3-4de0-4f88-814d-b69df33f7096	e69c9f21be2b53770b13ea52bf6c4f304a9fc86b41f1e932729ec2de45574341	2026-05-20 14:43:42.081072+00	20260520141718_baseline_diff	\N	\N	2026-05-20 14:43:42.077067+00	1
ee0a0611-692f-48ec-a16b-eb422ab7b764	e69c9f21be2b53770b13ea52bf6c4f304a9fc86b41f1e932729ec2de45574341	2026-05-19 22:53:15.768492+00	20260519225008_baseline_diff	\N	\N	2026-05-19 22:53:15.764892+00	1
145f13fd-91b0-4b61-af3e-fb57f7e0d106	e69c9f21be2b53770b13ea52bf6c4f304a9fc86b41f1e932729ec2de45574341	2026-05-19 23:04:02.22977+00	20260519225317_baseline_diff	\N	\N	2026-05-19 23:04:02.22666+00	1
dcb31989-e106-4009-9e96-4620e01038a2	e69c9f21be2b53770b13ea52bf6c4f304a9fc86b41f1e932729ec2de45574341	2026-05-19 23:27:42.404072+00	20260519230403_baseline_diff	\N	\N	2026-05-19 23:27:42.401008+00	1
be4affb1-36e9-4d87-b262-200c66284bd8	e69c9f21be2b53770b13ea52bf6c4f304a9fc86b41f1e932729ec2de45574341	2026-05-20 17:50:02.497081+00	20260520144343_baseline_diff	\N	\N	2026-05-20 17:50:02.493092+00	1
d967566c-4aae-431e-921b-66358dddae00	e69c9f21be2b53770b13ea52bf6c4f304a9fc86b41f1e932729ec2de45574341	2026-05-20 13:17:13.559196+00	20260520122953_baseline_diff	\N	\N	2026-05-20 13:17:13.555972+00	1
9117fdf6-6714-4249-a1bc-a37eb939ead5	e69c9f21be2b53770b13ea52bf6c4f304a9fc86b41f1e932729ec2de45574341	2026-05-20 13:35:57.765868+00	20260520131714_baseline_diff	\N	\N	2026-05-20 13:35:57.76192+00	1
092fb353-b83e-4b78-b4ea-e0022e1265f8	e69c9f21be2b53770b13ea52bf6c4f304a9fc86b41f1e932729ec2de45574341	2026-05-22 01:18:24.298101+00	20260521090213_baseline_diff	\N	\N	2026-05-22 01:18:24.291974+00	1
d2f5d070-4155-448f-a410-e5deb7b812f0	e69c9f21be2b53770b13ea52bf6c4f304a9fc86b41f1e932729ec2de45574341	2026-05-20 13:38:10.10185+00	20260520133559_baseline_diff	\N	\N	2026-05-20 13:38:10.098848+00	1
f44345a6-7d87-410d-a4fb-55f2c07fab81	e69c9f21be2b53770b13ea52bf6c4f304a9fc86b41f1e932729ec2de45574341	2026-05-20 18:05:01.49895+00	20260520175004_baseline_diff	\N	\N	2026-05-20 18:05:01.495472+00	1
09dcd4db-816c-46c4-8cf9-457a591beb8e	e69c9f21be2b53770b13ea52bf6c4f304a9fc86b41f1e932729ec2de45574341	2026-05-20 22:01:27.400222+00	20260520210027_baseline_diff	\N	\N	2026-05-20 22:01:27.396844+00	1
93eadb7c-cfd0-486b-bfff-f49dc87ff0c0	e69c9f21be2b53770b13ea52bf6c4f304a9fc86b41f1e932729ec2de45574341	2026-05-20 18:12:48.513378+00	20260520180503_baseline_diff	\N	\N	2026-05-20 18:12:48.510228+00	1
0de14496-de8e-46cb-8a29-560e4c75fb07	e69c9f21be2b53770b13ea52bf6c4f304a9fc86b41f1e932729ec2de45574341	2026-05-20 18:41:00.098088+00	20260520181250_baseline_diff	\N	\N	2026-05-20 18:41:00.094523+00	1
f2d9df7f-17d0-49cf-b138-ae4781f06a32	e69c9f21be2b53770b13ea52bf6c4f304a9fc86b41f1e932729ec2de45574341	2026-05-20 20:56:02.150171+00	20260520184102_baseline_diff	\N	\N	2026-05-20 20:56:02.146098+00	1
7c4dc307-e0c1-4566-af18-beb70be700de	e69c9f21be2b53770b13ea52bf6c4f304a9fc86b41f1e932729ec2de45574341	2026-05-20 22:02:37.207476+00	20260520220128_baseline_diff	\N	\N	2026-05-20 22:02:37.204534+00	1
6690448f-31f9-45b7-9047-c5d4bf96bb1b	e69c9f21be2b53770b13ea52bf6c4f304a9fc86b41f1e932729ec2de45574341	2026-05-20 20:56:38.005678+00	20260520205603_baseline_diff	\N	\N	2026-05-20 20:56:37.998046+00	1
28634d53-b05d-4e17-a2d8-51a0bef36e53	e69c9f21be2b53770b13ea52bf6c4f304a9fc86b41f1e932729ec2de45574341	2026-05-22 02:06:42.769472+00	20260522011825_baseline_diff	\N	\N	2026-05-22 02:06:42.766695+00	1
12ed40a8-0b94-4f5d-a733-a07b99645e23	e69c9f21be2b53770b13ea52bf6c4f304a9fc86b41f1e932729ec2de45574341	2026-05-20 23:05:12.25043+00	20260520220238_baseline_diff	\N	\N	2026-05-20 23:05:12.24506+00	1
111ccd49-d015-4bde-b0dc-c2cb6933c140	e69c9f21be2b53770b13ea52bf6c4f304a9fc86b41f1e932729ec2de45574341	2026-05-20 23:05:47.199443+00	20260520230513_baseline_diff	\N	\N	2026-05-20 23:05:47.195939+00	1
8a7cd159-a3d2-43f6-9f50-e4ef8af987ec	e69c9f21be2b53770b13ea52bf6c4f304a9fc86b41f1e932729ec2de45574341	2026-05-23 10:44:43.790136+00	20260523100035_baseline_diff	\N	\N	2026-05-23 10:44:43.787844+00	1
4ea98f11-d9ea-4f16-8503-17ab445808fe	e69c9f21be2b53770b13ea52bf6c4f304a9fc86b41f1e932729ec2de45574341	2026-05-22 02:13:27.889671+00	20260522020644_baseline_diff	\N	\N	2026-05-22 02:13:27.885878+00	1
834fe37f-95f3-4ebc-9599-3b310f1e898d	e69c9f21be2b53770b13ea52bf6c4f304a9fc86b41f1e932729ec2de45574341	2026-05-23 10:00:34.391648+00	20260522021329_baseline_diff	\N	\N	2026-05-23 10:00:34.387659+00	1
3bd595c9-f550-4a0a-96f1-a88177ef17af	e69c9f21be2b53770b13ea52bf6c4f304a9fc86b41f1e932729ec2de45574341	2026-05-26 01:50:55.839134+00	20260523104445_baseline_diff	\N	\N	2026-05-26 01:50:55.835155+00	1
cfafed48-7341-4a5c-b075-7cc8fed6e449	e69c9f21be2b53770b13ea52bf6c4f304a9fc86b41f1e932729ec2de45574341	2026-05-26 19:41:49.938057+00	20260526191932_baseline_diff	\N	\N	2026-05-26 19:41:49.933491+00	1
c4714845-16b5-4244-838f-b94b1d69e677	e69c9f21be2b53770b13ea52bf6c4f304a9fc86b41f1e932729ec2de45574341	2026-05-27 19:26:50.152856+00	20260526195829_baseline_diff	\N	\N	2026-05-27 19:26:50.150112+00	1
8bf8949b-d000-41f2-9ff8-b13e74b7cd2a	e69c9f21be2b53770b13ea52bf6c4f304a9fc86b41f1e932729ec2de45574341	2026-05-27 19:28:22.520598+00	20260527192651_baseline_diff	\N	\N	2026-05-27 19:28:22.517297+00	1
23a99fad-8a29-4401-a802-16f9943d74d5	e69c9f21be2b53770b13ea52bf6c4f304a9fc86b41f1e932729ec2de45574341	2026-05-27 19:30:59.100567+00	20260527192823_baseline_diff	\N	\N	2026-05-27 19:30:59.097286+00	1
4c1d8c5e-7f21-4c5a-ae20-d44e890af643	e69c9f21be2b53770b13ea52bf6c4f304a9fc86b41f1e932729ec2de45574341	2026-05-27 19:32:19.331926+00	20260527193100_baseline_diff	\N	\N	2026-05-27 19:32:19.329275+00	1
6f3def57-c5ae-4bf0-9e78-2015c91baf5b	e69c9f21be2b53770b13ea52bf6c4f304a9fc86b41f1e932729ec2de45574341	2026-05-27 20:06:57.182906+00	20260527193220_baseline_diff	\N	\N	2026-05-27 20:06:57.179829+00	1
15a557bd-39c4-49a7-a278-7ffae115cb6f	e69c9f21be2b53770b13ea52bf6c4f304a9fc86b41f1e932729ec2de45574341	2026-06-01 20:45:00.711637+00	20260601204148_baseline_diff	\N	\N	2026-06-01 20:45:00.707767+00	1
c4622c9b-5572-4951-90df-50b9e5a547a6	e69c9f21be2b53770b13ea52bf6c4f304a9fc86b41f1e932729ec2de45574341	2026-06-01 21:24:06.606598+00	20260601204502_baseline_diff	\N	\N	2026-06-01 21:24:06.603642+00	1
051d8732-cdd1-4d78-bb5a-baed41c27f84	e69c9f21be2b53770b13ea52bf6c4f304a9fc86b41f1e932729ec2de45574341	2026-06-01 21:25:56.242798+00	20260601212408_baseline_diff	\N	\N	2026-06-01 21:25:56.239529+00	1
c1bbd0d7-5482-4aa5-8a24-0e14cefeeb37	e69c9f21be2b53770b13ea52bf6c4f304a9fc86b41f1e932729ec2de45574341	2026-06-01 21:29:27.289837+00	20260601212557_baseline_diff	\N	\N	2026-06-01 21:29:27.287157+00	1
82725544-e4a4-4afd-b572-98d9c338f487	e69c9f21be2b53770b13ea52bf6c4f304a9fc86b41f1e932729ec2de45574341	2026-06-01 21:32:35.265922+00	20260601212928_baseline_diff	\N	\N	2026-06-01 21:32:35.262535+00	1
27ca3b62-5d8e-4bac-8c38-d622c77af879	e69c9f21be2b53770b13ea52bf6c4f304a9fc86b41f1e932729ec2de45574341	2026-06-01 22:35:08.770334+00	20260601213236_baseline_diff	\N	\N	2026-06-01 22:35:08.766832+00	1
24be4f3a-1de2-42c3-b1b1-dc805ad3482e	e69c9f21be2b53770b13ea52bf6c4f304a9fc86b41f1e932729ec2de45574341	2026-06-02 01:17:01.545672+00	20260601223510_baseline_diff	\N	\N	2026-06-02 01:17:01.54153+00	1
ebfbf60f-08ad-4777-b2e5-9ec48a78c1ff	e69c9f21be2b53770b13ea52bf6c4f304a9fc86b41f1e932729ec2de45574341	2026-06-03 01:35:34.546038+00	20260602011703_baseline_diff	\N	\N	2026-06-03 01:35:34.542692+00	1
da4e0103-4ee8-43c9-95c2-44b93c0a317c	e69c9f21be2b53770b13ea52bf6c4f304a9fc86b41f1e932729ec2de45574341	2026-06-03 01:42:51.082948+00	20260603013535_baseline_diff	\N	\N	2026-06-03 01:42:51.079477+00	1
6344b444-3674-4539-a46e-bf137056f380	e69c9f21be2b53770b13ea52bf6c4f304a9fc86b41f1e932729ec2de45574341	2026-06-03 12:45:49.156742+00	20260603014252_baseline_diff	\N	\N	2026-06-03 12:45:49.153573+00	1
dc32491b-c703-4033-b985-a850b2fcd537	e69c9f21be2b53770b13ea52bf6c4f304a9fc86b41f1e932729ec2de45574341	2026-06-03 18:50:05.488828+00	20260603124550_baseline_diff	\N	\N	2026-06-03 18:50:05.485342+00	1
78c0fd8c-e7f3-4704-a782-74bb337c52dd	d0310ee9b45b9881773946f09b1c4ba184586f851b106bca1be0d0014b8e1d66	\N	20260603185007_baseline_diff	A migration failed to apply. New migrations cannot be applied before the error is recovered from. Read more about how to resolve migration issues in a production database: https://pris.ly/d/migrate-resolve\n\nMigration name: 20260603185007_baseline_diff\n\nDatabase error code: 42P01\n\nDatabase error:\nERROR: table "credential_inventory" does not exist\n\nDbError { severity: "ERROR", parsed_severity: Some(Error), code: SqlState(E42P01), message: "table \\"credential_inventory\\" does not exist", detail: None, hint: None, position: None, where_: None, schema: None, table: None, column: None, datatype: None, constraint: None, file: Some("tablecmds.c"), line: Some(1421), routine: Some("DropErrorMsgNonExistent") }\n\n   0: sql_schema_connector::apply_migration::apply_script\n           with migration_name="20260603185007_baseline_diff"\n             at schema-engine/connectors/sql-schema-connector/src/apply_migration.rs:106\n   1: schema_core::commands::apply_migrations::Applying migration\n           with migration_name="20260603185007_baseline_diff"\n             at schema-engine/core/src/commands/apply_migrations.rs:91\n   2: schema_core::state::ApplyMigrations\n             at schema-engine/core/src/state.rs:201	2026-06-03 21:25:42.473365+00	2026-06-03 21:25:36.268488+00	0
2e324777-8423-4bc8-ba53-bb14808331ea	d0310ee9b45b9881773946f09b1c4ba184586f851b106bca1be0d0014b8e1d66	2026-06-03 21:25:49.212926+00	20260603185007_baseline_diff		\N	2026-06-03 21:25:49.212926+00	0
ceda7056-07ea-4429-a565-96c90a74bd2e	e69c9f21be2b53770b13ea52bf6c4f304a9fc86b41f1e932729ec2de45574341	2026-06-04 16:26:31.947351+00	20260604042818_baseline_diff	\N	\N	2026-06-04 16:26:31.943876+00	1
80909fa3-d344-4237-9495-8e53c30d22d6	686be79c5c68c056c7473f27374767ae6c952fe09e95ea7b8dd13047a09fad8b	2026-06-05 00:18:18.407642+00	20260421135425_add_team_membership_total_spend	\N	\N	2026-06-05 00:18:18.405649+00	1
b18648ba-37e9-4c32-bbf6-d510ab2de19f	552e04c0e6590ef1b2e9d0e1a181e3c98d83581ae57ab4e292aafa76a54af1fb	2026-06-05 00:18:18.368607+00	20260319000000_restore_mcp_approval_fields	\N	\N	2026-06-05 00:18:18.362651+00	1
818479c6-1115-4404-b8e4-701914fc6ffc	4b151c1a923781877f3666157d5463a1e0c565dad6c20e73eb8840b76c5bf9a0	2026-06-05 00:18:18.374637+00	20260321000000_add_mcp_toolsets	\N	\N	2026-06-05 00:18:18.369288+00	1
0e542eb0-142c-4315-bf2f-2fa7d353ba31	52db3f7f88c3073debc15024e2d3c448a294510531d5189a9fe7d6cbfc44756b	2026-06-05 00:18:18.379228+00	20260331000000_add_prompt_environment_and_created_by	\N	\N	2026-06-05 00:18:18.375162+00	1
3ec20360-3986-461a-9b1e-31b9030e4ca5	dab418bc243b4a928ca2fca2a49621900c1d2223fde0aa5c9c6027ca2d8b5558	2026-06-05 00:18:18.410169+00	20260429120000_search_tools_on_object_permission	\N	\N	2026-06-05 00:18:18.408316+00	1
059805cb-5b90-4eba-b063-13b7bbd4970e	ef1161b00f477701b08b9868c8ca4b41266765a946c3adda8530d810db7bc7c5	2026-06-05 00:18:18.384036+00	20260401000000_add_budget_limits	\N	\N	2026-06-05 00:18:18.380826+00	1
a75c272d-459d-48e7-953b-07b9c12c6155	4872cb4220d148cc96b4a17e8673566891ebdd804a576112db705147bc9c1a2f	2026-06-05 00:18:18.387825+00	20260401000000_add_team_member_model_scope	\N	\N	2026-06-05 00:18:18.384808+00	1
c7d0ae58-f13c-432f-9302-bc5ecda0ed7c	076b759528c1065b535472c6694bbdeb7d6b0b5446f3df26ea68aac3294c49b1	2026-06-05 00:18:18.390314+00	20260414140000_add_mcp_server_instructions	\N	\N	2026-06-05 00:18:18.388521+00	1
239286a2-9fda-4ce7-9191-076b54bf50e6	6293c4f78ea52d9e64503a0b284e9da960dd6351ffe2210b74ec5494607c6f67	2026-06-05 00:18:18.4203+00	20260429161855_workflow_runs_tables	\N	\N	2026-06-05 00:18:18.410967+00	1
743c7574-0539-4180-8a2a-4c523395c3f5	e5dce697bc2b61744f058f64892ebd7ef4112a46fc82ba42cd6104785e977ccb	2026-06-05 00:18:18.394069+00	20260415120000_health_check_latest_per_model_index	\N	\N	2026-06-05 00:18:18.391089+00	1
417009e5-ae13-47de-aef9-f86df316e77a	b49bdecc8510bbe30eb3810761cbde182a37575cd012e38fff60829a3c32e8a7	2026-06-05 00:18:18.400736+00	20260418000000_add_adaptive_router_tables	\N	\N	2026-06-05 00:18:18.394848+00	1
401db1f6-0828-4d17-b849-27d12a4325a3	a39a409b748dc9c65ab7f182cc668d21c89a8489f1859899056fab60a7c8ba1e	2026-06-05 00:18:18.404965+00	20260421120000_add_memory_table	\N	\N	2026-06-05 00:18:18.401455+00	1
e4d228f5-ec22-48bf-946f-c280723f709b	70a413cf659a8263cc4cc3d90942fa13c11569f6a29dac63aabfe53791ea7f57	2026-06-05 00:18:18.424637+00	20260501195714_managed_resource_team_owner	\N	\N	2026-06-05 00:18:18.421061+00	1
39381536-b8b2-438e-bebb-51c32e64b135	8edde816aef67759bbdb455276a3aa02e15e2e96892d8623cdb58092d393992e	2026-06-05 00:18:18.427185+00	20260513120000_add_delegate_auth_to_upstream_to_mcp_servers	\N	\N	2026-06-05 00:18:18.425303+00	1
1ecb15d9-6ba9-4cef-bb5a-31f6d5d072c8	6079a465b829311a62c9fccc9c15447754841e683b3862551819d02cc59868fc	2026-06-05 00:18:18.429733+00	20260514120000_add_blocked_to_proxy_model_table	\N	\N	2026-06-05 00:18:18.427881+00	1
\.


--
-- PostgreSQL database dump complete
--

\unrestrict 5yElRueMjx06XOnondWLNzq64BEYxmU9eE4JsHNq8bYWDXCQRRMNj7zYcW5svVe

