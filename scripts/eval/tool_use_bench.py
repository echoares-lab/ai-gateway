#!/usr/bin/env python3
"""Claude Code tool-use fidelity benchmark harness.

Runs the `claude` CLI headlessly against a scratch git repo seeded from a
fixture under scripts/eval/fixtures/<task>/, pointed at a local gateway dev
slot, for each requested model, and records apply-success / correctness /
model-fallback-substitution per run.

See docs/tool-use-eval.md for the design this implements.
"""
from __future__ import annotations

import argparse
import importlib.util
import json
import shutil
import subprocess
import sys
import tempfile
import time
from pathlib import Path

FIXTURES_DIR = Path(__file__).parent / "fixtures"
DEFAULT_MODELS = ["claude-sonnet-4-6", "gpt-5-4", "gemini-3-flash"]
DEFAULT_TASKS = ["single_edit"]


def load_checker(task_dir: Path):
    spec = importlib.util.spec_from_file_location(f"checker_{task_dir.name}", task_dir / "checker.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)  # type: ignore[union-attr]
    return module.check


def seed_scratch_dir(task_dir: Path) -> Path:
    scratch = Path(tempfile.mkdtemp(prefix="tool-use-eval-"))
    for item in task_dir.iterdir():
        if item.name in ("task_prompt.txt", "checker.py"):
            continue
        if item.is_file():
            shutil.copy2(item, scratch / item.name)
        else:
            shutil.copytree(item, scratch / item.name)
    subprocess.run(["git", "init", "-q"], cwd=scratch, check=True)
    subprocess.run(["git", "add", "-A"], cwd=scratch, check=True)
    subprocess.run(
        ["git", "-c", "user.email=eval@local", "-c", "user.name=eval", "commit", "-q", "-m", "seed"],
        cwd=scratch,
        check=True,
    )
    return scratch


def run_once(model: str, task: str, base_url: str, api_key: str, timeout_s: int) -> dict:
    task_dir = FIXTURES_DIR / task
    prompt = (task_dir / "task_prompt.txt").read_text()
    checker = load_checker(task_dir)
    scratch = seed_scratch_dir(task_dir)

    record: dict = {
        "model_requested": model,
        "task": task,
        "scratch_dir": str(scratch),
        "started_at": time.time(),
    }

    try:
        proc = subprocess.run(
            [
                "claude",
                "-p",
                prompt,
                "--model",
                f"AI-Gateway:{model}",
                "--output-format",
                "json",
                "--permission-mode",
                "bypassPermissions",
                "--no-session-persistence",
            ],
            cwd=scratch,
            env={
                "ANTHROPIC_BASE_URL": base_url,
                "ANTHROPIC_API_KEY": api_key,
                "PATH": "/usr/bin:/bin:/usr/local/bin:/home/dev/.npm-global/bin",
                "HOME": "/home/dev",
            },
            capture_output=True,
            text=True,
            timeout=timeout_s,
        )
    except subprocess.TimeoutExpired:
        record.update(apply_success=False, correct=False, fallback_substituted=None,
                      error=f"timed out after {timeout_s}s")
        shutil.rmtree(scratch, ignore_errors=True)
        return record

    record["returncode"] = proc.returncode
    record["stderr_tail"] = proc.stderr[-2000:]

    try:
        result_json = json.loads(proc.stdout.strip().splitlines()[-1]) if proc.stdout.strip() else {}
    except (json.JSONDecodeError, IndexError):
        result_json = {}
        record["raw_stdout_tail"] = proc.stdout[-2000:]

    model_usage_keys = list(result_json.get("modelUsage", {}).keys())
    requested_key = f"AI-Gateway:{model}"
    fallback_substituted = bool(model_usage_keys) and requested_key not in model_usage_keys
    record["model_usage_keys"] = model_usage_keys
    record["fallback_substituted"] = fallback_substituted
    record["is_error"] = result_json.get("is_error")
    record["stop_reason"] = result_json.get("stop_reason")
    record["result_text"] = result_json.get("result")

    apply_success = proc.returncode == 0 and result_json.get("is_error") is False
    record["apply_success"] = apply_success

    if fallback_substituted:
        record["correct"] = None  # excluded from scorecard per pilot's fallback guard
    elif apply_success:
        ok, reason = checker(scratch)
        record["correct"] = ok
        record["check_reason"] = reason
    else:
        record["correct"] = False
        record["check_reason"] = "apply failed"

    shutil.rmtree(scratch, ignore_errors=True)
    return record


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--models", default=",".join(DEFAULT_MODELS))
    parser.add_argument("--tasks", default=",".join(DEFAULT_TASKS))
    parser.add_argument("--repeats", type=int, default=2)
    parser.add_argument("--base-url", default="http://localhost:4010")
    parser.add_argument("--api-key", required=True)
    parser.add_argument("--timeout", type=int, default=120)
    parser.add_argument("--out", default="tool_use_bench_results.jsonl")
    args = parser.parse_args()

    models = [m.strip() for m in args.models.split(",") if m.strip()]
    tasks = [t.strip() for t in args.tasks.split(",") if t.strip()]

    records = []
    out_path = Path(args.out)
    with out_path.open("w") as f:
        for task in tasks:
            for model in models:
                for rep in range(args.repeats):
                    print(f"[run] task={task} model={model} rep={rep + 1}/{args.repeats}", file=sys.stderr)
                    rec = run_once(model, task, args.base_url, args.api_key, args.timeout)
                    rec["rep"] = rep
                    records.append(rec)
                    f.write(json.dumps(rec) + "\n")
                    f.flush()

    # Scorecard: model x task -> "pass/total (excluded)"
    cells: dict[tuple[str, str], dict] = {}
    for rec in records:
        key = (rec["model_requested"], rec["task"])
        cell = cells.setdefault(key, {"pass": 0, "total": 0, "excluded": 0})
        if rec.get("fallback_substituted"):
            cell["excluded"] += 1
            continue
        cell["total"] += 1
        if rec.get("correct"):
            cell["pass"] += 1

    print("\n## Scorecard\n")
    print("| Model | Task | Pass/Total | Excluded (fallback-substituted) |")
    print("|---|---|---|---|")
    for (model, task), cell in sorted(cells.items()):
        print(f"| {model} | {task} | {cell['pass']}/{cell['total']} | {cell['excluded']} |")

    print(f"\nRaw JSONL log: {out_path}")


if __name__ == "__main__":
    main()
