# Repo Improvement Appendix: AI Gateway

Repo-specific operating details for `REPO_IMPROVEMENT_WORKFLOW.md`.

## Branch and worktree policy

```text
main -> feat/* worktree/branch -> PR -> main
```

- Create feature worktrees from `main`, not a long-lived `dev` branch.
- Do not edit the stable worktree at `/home/dev/repos/ai-gateway` for feature work.
- Keep slot 0 reserved for the stable stack.
- Use a separate dev stack slot for work that needs live-service validation.

## Environment strategy

- Stable stack: port 4000.
- Dev stacks: `./dev-env.sh start <slot>`.
- Slot 1 maps translator to port 4010; slot 2 maps translator to port 4020.
- Translator changes hot-reload through uvicorn.
- `litellm-config.yaml` changes are picked up by the LiteLLM reloader.

## Required checks

- Translator unit tests: `docker exec aidev<slot>-translator-1 pytest test_translator.py -v`.
- Integration tests: `./dev-env.sh test <slot>`.
- Health check: `./cliproxy-setup.sh health`.
- YAML validation: `python3 -c "import yaml; yaml.safe_load(open('litellm-config.yaml'))"`.
- Shell syntax for changed shell scripts: `bash -n <script>`.

## Manual E2E verification

- `./cliproxy-setup.sh test claude-sonnet-4-6`.
- `./cliproxy-setup.sh test gemini-3-flash`.
- `./cliproxy-setup.sh test gpt-5-4`.

## Hotspot files and areas

- `services/translator/translator.py`.
- `litellm-config.yaml`.
- `docker-compose.yml` and `docker-compose.dev.yml`.
- `cliproxy-setup.sh` and `dev-env.sh`.
- `.github/workflows/`.

## Useful commands

- `./dev-env.sh list`.
- `./dev-env.sh start <slot>`.
- `./dev-env.sh stop <slot>`.
- `./dev-env.sh test <slot>`.
- `./cliproxy-setup.sh quota-summary`.
- `./cliproxy-setup.sh sync-models`.
