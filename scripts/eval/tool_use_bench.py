#!/usr/bin/env python3
"""Cross-Model Tool-Use Evaluation Benchmark runner (Epic #420)."""

import os
import subprocess
import sys
import tempfile
import time

# Force import compatibility path
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "../../services/gateway-engine")))


def run_benchmark():
    print("=============================================================")
    print("Starting Cross-Model Tool-Use Benchmark (Epic #420)")
    print("=============================================================")

    # 1. Start mock upstream on port 5001
    print("Starting Mock Upstream on port 5001...")
    upstream_proc = subprocess.Popen([sys.executable, "scripts/eval/mock_upstream.py"])
    time.sleep(2)  # Wait for startup

    # Define tasks and models to test
    models = ["claude-sonnet-4-6", "gpt-5-4", "gemini-3-flash"]

    # Store scorecard results
    scorecard = {model: {} for model in models}

    try:
        # Task 1: single-edit
        for model in models:
            print(f"\n--- Running Task: single-edit for Model: {model} ---")

            # Start gateway-engine on port 5002 with model override env var
            gateway_env = os.environ.copy()
            gateway_env["LITELLM_URL"] = "http://127.0.0.1:5001"
            gateway_env["ALLOW_DEV_MODEL_FORCE"] = "true"
            gateway_env["FORCE_MODEL_OVERRIDE"] = model
            gateway_env["POLICY_ENGINE_ENABLED"] = "false"
            gateway_env["CACHE_ENABLED"] = "false"

            gateway_proc = subprocess.Popen(
                [
                    sys.executable,
                    "-m",
                    "uvicorn",
                    "main:app",
                    "--host",
                    "127.0.0.1",
                    "--port",
                    "5002",
                    "--workers",
                    "1",
                ],
                cwd="services/gateway-engine",
                env=gateway_env,
            )
            time.sleep(2)  # Wait for startup

            # Setup temp workspace
            with tempfile.TemporaryDirectory() as tmpdir:
                file_path = os.path.join(tmpdir, "file.txt")
                with open(file_path, "w") as f:
                    f.write("Hello World\nLine 2\nLine 3\n")

                # Configure client environment
                client_env = os.environ.copy()
                client_env["ANTHROPIC_BASE_URL"] = "http://127.0.0.1:5002"
                client_env["ANTHROPIC_API_KEY"] = "sk-ant-test-key-12345"

                cmd = [
                    "claude",
                    "-p",
                    f"Please edit {file_path} to replace 'Hello' with 'Bonjour'.",
                    "--tools",
                    "Read,Edit",
                    "--permission-mode",
                    "bypassPermissions",
                    "--no-session-persistence",
                ]

                print(f"Executing: {' '.join(cmd)}")
                try:
                    res = subprocess.run(
                        cmd, cwd=tmpdir, env=client_env, stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=15
                    )
                    print(f"STDOUT:\n{res.stdout.decode('utf-8', errors='replace')}")
                    print(f"STDERR:\n{res.stderr.decode('utf-8', errors='replace')}")
                except subprocess.TimeoutExpired:
                    print("Timeout expired for Claude command execution.")

                # Read output file state
                with open(file_path, "r") as f:
                    content = f.read()

                print(f"Resulting file content:\n{content}")

                # Check pass criteria
                success = "Bonjour World" in content
                scorecard[model]["single-edit"] = "PASS" if success else "FAIL"

            # Stop gateway-engine for this iteration
            gateway_proc.terminate()
            gateway_proc.wait()

        # Task 2: write-file
        for model in models:
            print(f"\n--- Running Task: write-file for Model: {model} ---")

            # Start gateway-engine on port 5002 with model override env var
            gateway_env = os.environ.copy()
            gateway_env["LITELLM_URL"] = "http://127.0.0.1:5001"
            gateway_env["ALLOW_DEV_MODEL_FORCE"] = "true"
            gateway_env["FORCE_MODEL_OVERRIDE"] = model
            gateway_env["POLICY_ENGINE_ENABLED"] = "false"
            gateway_env["CACHE_ENABLED"] = "false"

            gateway_proc = subprocess.Popen(
                [
                    sys.executable,
                    "-m",
                    "uvicorn",
                    "main:app",
                    "--host",
                    "127.0.0.1",
                    "--port",
                    "5002",
                    "--workers",
                    "1",
                ],
                cwd="services/gateway-engine",
                env=gateway_env,
            )
            time.sleep(2)  # Wait for startup

            with tempfile.TemporaryDirectory() as tmpdir:
                new_file_path = os.path.join(tmpdir, "new.txt")

                client_env = os.environ.copy()
                client_env["ANTHROPIC_BASE_URL"] = "http://127.0.0.1:5002"
                client_env["ANTHROPIC_API_KEY"] = "sk-ant-test-key-12345"

                cmd = [
                    "claude",
                    "-p",
                    f"Please create a new file named {new_file_path} with welcome text.",
                    "--tools",
                    "Write",
                    "--permission-mode",
                    "bypassPermissions",
                    "--no-session-persistence",
                ]

                print(f"Executing: {' '.join(cmd)}")
                try:
                    res = subprocess.run(
                        cmd, cwd=tmpdir, env=client_env, stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=15
                    )
                    print(f"STDOUT:\n{res.stdout.decode('utf-8', errors='replace')}")
                    print(f"STDERR:\n{res.stderr.decode('utf-8', errors='replace')}")
                except subprocess.TimeoutExpired:
                    print("Timeout expired for Claude command execution.")

                # Verify file creation
                success = os.path.exists(new_file_path)
                if success:
                    with open(new_file_path, "r") as f:
                        file_text = f.read()
                    print(f"Resulting new.txt content:\n{file_text}")

                scorecard[model]["write-file"] = "PASS" if success else "FAIL"

            # Stop gateway-engine for this iteration
            gateway_proc.terminate()
            gateway_proc.wait()

    finally:
        print("\nCleaning up processes...")
        upstream_proc.terminate()
        upstream_proc.wait()

    # 3. Output Scorecard Report
    print("\n=============================================================")
    print("TOOL-USE FIDELITY BENCHMARK SCORECARD")
    print("=============================================================")
    print("| Model | single-edit | write-file |")
    print("|---|---|---|")
    for model in models:
        se = scorecard[model].get("single-edit", "N/A")
        wf = scorecard[model].get("write-file", "N/A")
        print(f"| {model} | {se} | {wf} |")
    print("=============================================================\n")


if __name__ == "__main__":
    run_benchmark()
