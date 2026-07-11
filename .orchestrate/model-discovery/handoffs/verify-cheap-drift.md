<!-- orchestrate handoff
task: verify-cheap-drift
branch: orch/model-discovery/cheap-drift
agentId: bc-4ec2e528-1972-48f2-8b77-9424aa97fc8f
runId: run-4de39c44-9775-4f9f-bcfb-09769e2b17b6
resultStatus: finished
finishedAt: 2026-07-11T09:40:47.978Z
-->

All verification complete. Every acceptance criterion reproduced by observable behavior.

## Verification
unit-test-verified

## Target
`cheap-drift` on branch `orch/model-discovery/cheap-drift`

## Branch
`orch/model-discovery/cheap-drift`

## Execution
- `python3 -m pip install pytest` → installed (not preinstalled), pytest 9.1.1
- `python3 -m pytest tests/test_cheap_drift_check.py -v` → **3 passed, 0 failed** (`test_no_drift_exits_zero`, `test_drift_over_threshold_exits_non_zero`, `test_offline_catalog_file_parsing_and_normalization`)
- `make drift-cheap` → executed `scripts/cheap_drift_check.py` in offline fixture mode; `total_drift_count=0`, `within_threshold=true`, **exit 0**
- Manual drifted catalog (missing `claude-sonnet-4-6`, extra `extra-model`; drift=2):
  - default threshold 0 → **exit 1** (over) ✓
  - `--threshold 5` → **exit 0** (within) ✓
  - `--threshold 2` (== drift) → **exit 0** (uses `<=`) ✓
  - `--threshold 1` → **exit 1** (over) ✓
- `rg -n 'chat/completions|max_tokens|completions|messages|prompt' scripts/cheap_drift_check.py` → **no matches**; only HTTP in script is `GET {CLIPROXY_URL}/v1/models` (catalog listing, zero token cost)
- `git diff --name-only d4a621b HEAD` → Makefile, scripts/cheap_drift_check.py, tests/* only; **no `services/**` changes**
- `gh pr view 368` → **OPEN, draft, base `main`, head `orch/model-discovery/cheap-drift`**

## Findings
Per acceptance criterion:
- [x] `scripts/cheap_drift_check.py` compares configured vs served sets with zero chat-completion calls: pure set difference in `build_report`; grep found no probe patterns; only endpoint is `/v1/models` (**met**)
- [x] Offline mode via `--catalog-file` works and covered by passing pytest: `make drift-cheap` and all 3 tests use `--catalog-file` and pass (**met**)
- [x] `make drift-cheap` runs the checker: confirmed, exit 0 (**met**)
- [x] Exit code non-zero when drift exceeds `--threshold`, zero when within: verified across 4 threshold cases (**met**)
- [x] A draft PR against main is opened: PR #368 OPEN, draft, base main (**met**)
- [x] Verifier: Verification section includes execution evidence for all criteria (**met**)

Other findings:
- (low) JSON report includes `configured_not_served`, `served_not_configured`, counts, threshold, sources, and normalization note — matches plan.
- (low) Alias normalization gotcha handled: config `gpt-5-4` matches served `gpt-5.4` (lowercase + `.`→`-`), yielding no false drift; verified live and in the normalization test.
- (low) `within_threshold` uses `<=` (drift == threshold passes); consistent with "exceeds threshold" wording.

## Notes & suggestions
- Upstream handoff's garbled measurement line (`2 failed, 1 passed → 3 passed`) does not reflect the final state — the committed suite is a clean 3/3 pass. Likely an intermediate-vs-final artifact; no concern.
- pytest is not in the base image; CI/other agents will need to install it. Suggest ensuring the test tier installs pytest.
- No live CLIProxy path exercised (no running stack/creds), but that path is out of scope for the "cheap/offline" criteria and requires no probing anyway.
- Committed verifier audit note `.verifier-cheap-drift-audit.md` to the branch; did not modify any target source files, and did not merge/rebase/PR.