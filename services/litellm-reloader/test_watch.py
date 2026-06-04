"""Unit tests for watch.py pre-flight validation logic.

Run inside the litellm-reloader container:
    python /app/test_watch.py
"""

import os
import sys
import tempfile
import unittest

# Patch the environment so watch.py doesn't need Docker or watchfiles at import
os.environ.setdefault("CONFIG_PATH", "/tmp/test-config.yaml")

# Import the module under test
sys.path.insert(0, "/app")
import watch  # noqa: E402  (watch.py is in /app)


class TestValidateModelList(unittest.TestCase):
    def test_valid_model_list(self):
        models = [
            {"model_name": "claude-opus-4-7", "litellm_params": {"model": "openai/claude-opus-4-7"}},
            {"model_name": "gpt-5-4", "litellm_params": {"model": "openai/gpt-5-4"}},
        ]
        errors = watch._validate_model_list(models)
        self.assertEqual(errors, [], f"Expected no errors, got: {errors}")

    def test_not_a_list(self):
        errors = watch._validate_model_list({"model_name": "bad"})
        self.assertEqual(len(errors), 1)
        self.assertIn("must be a list", errors[0])

    def test_missing_model_name(self):
        models = [{"litellm_params": {"model": "x"}}]
        errors = watch._validate_model_list(models)
        self.assertTrue(any("model_name" in e for e in errors))

    def test_missing_litellm_params(self):
        models = [{"model_name": "x"}]
        errors = watch._validate_model_list(models)
        self.assertTrue(any("litellm_params" in e for e in errors))

    def test_entry_not_dict(self):
        errors = watch._validate_model_list(["just-a-string"])
        self.assertTrue(any("must be a dict" in e for e in errors))

    def test_both_keys_missing(self):
        models = [{}]
        errors = watch._validate_model_list(models)
        self.assertEqual(len(errors), 2)


class TestValidateMcpServers(unittest.TestCase):
    def test_valid_stdio_server(self):
        mcp = {
            "mcp-filesystem": {
                "command": "npx",
                "args": ["-y", "@modelcontextprotocol/server-filesystem", "/tmp"],
            }
        }
        errors = watch._validate_mcp_servers(mcp)
        self.assertEqual(errors, [], f"Expected no errors, got: {errors}")

    def test_valid_stdio_server_with_env(self):
        mcp = {
            "mcp-brave": {
                "command": "npx",
                "args": ["-y", "@modelcontextprotocol/server-brave"],
                "env": {"BRAVE_API_KEY": "os.environ/BRAVE_API_KEY"},
            }
        }
        errors = watch._validate_mcp_servers(mcp)
        self.assertEqual(errors, [], f"Expected no errors, got: {errors}")

    def test_valid_sse_server(self):
        mcp = {
            "my-sse-server": {
                "url": "https://my-server.example.com/sse",
                "transport": "sse",
            }
        }
        errors = watch._validate_mcp_servers(mcp)
        self.assertEqual(errors, [], f"Expected no errors, got: {errors}")

    def test_valid_http_sse_server_no_transport(self):
        mcp = {"my-http-server": {"url": "http://localhost:8080/sse"}}
        errors = watch._validate_mcp_servers(mcp)
        self.assertEqual(errors, [], f"Expected no errors, got: {errors}")

    def test_sse_bad_url_scheme(self):
        mcp = {"bad-sse": {"url": "ftp://bad-server.com/sse"}}
        errors = watch._validate_mcp_servers(mcp)
        self.assertTrue(any("http://" in e or "https://" in e for e in errors))

    def test_stdio_empty_command(self):
        mcp = {"bad-stdio": {"command": ""}}
        errors = watch._validate_mcp_servers(mcp)
        self.assertTrue(any("command" in e for e in errors))

    def test_stdio_args_not_list(self):
        mcp = {"bad-args": {"command": "npx", "args": "not-a-list"}}
        errors = watch._validate_mcp_servers(mcp)
        self.assertTrue(any("args" in e for e in errors))

    def test_stdio_args_contains_non_string(self):
        mcp = {"bad-args": {"command": "npx", "args": ["-y", 123]}}
        errors = watch._validate_mcp_servers(mcp)
        self.assertTrue(any("args" in e for e in errors))

    def test_stdio_env_not_dict(self):
        mcp = {"bad-env": {"command": "npx", "env": ["not", "a", "dict"]}}
        errors = watch._validate_mcp_servers(mcp)
        self.assertTrue(any("env" in e for e in errors))

    def test_no_command_or_url(self):
        mcp = {"nothing": {"some_key": "some_value"}}
        errors = watch._validate_mcp_servers(mcp)
        self.assertTrue(any("command" in e or "url" in e for e in errors))

    def test_not_a_dict(self):
        errors = watch._validate_mcp_servers("not-a-dict")
        self.assertTrue(any("must be a dict" in e for e in errors))


class TestValidateConfig(unittest.TestCase):
    def _write_config(self, content: str) -> str:
        f = tempfile.NamedTemporaryFile(mode="w", suffix=".yaml", delete=False)
        f.write(content)
        f.flush()
        f.close()
        return f.name

    def test_valid_minimal_config(self):
        path = self._write_config(
            "model_list:\n  - model_name: test-model\n    litellm_params:\n      model: openai/test-model\n"
        )
        result = watch.validate_config(path)
        os.unlink(path)
        self.assertTrue(result)

    def test_valid_full_config(self):
        path = self._write_config(
            "model_list:\n"
            "  - model_name: gpt-5-4\n"
            "    litellm_params:\n"
            "      model: openai/gpt-5-4\n"
            "litellm_settings:\n"
            "  mcp_servers:\n"
            "    mcp-fs:\n"
            "      command: npx\n"
            '      args: ["-y", "@modelcontextprotocol/server-filesystem", "/tmp"]\n'
        )
        result = watch.validate_config(path)
        os.unlink(path)
        self.assertTrue(result)

    def test_invalid_yaml_syntax(self):
        path = self._write_config("model_list:\n  - model_name: test\n    bad: : : :\n")
        result = watch.validate_config(path)
        os.unlink(path)
        self.assertFalse(result)

    def test_missing_model_name_blocks_restart(self):
        path = self._write_config("model_list:\n  - litellm_params:\n      model: openai/test\n")
        result = watch.validate_config(path)
        os.unlink(path)
        self.assertFalse(result)

    def test_missing_litellm_params_blocks_restart(self):
        path = self._write_config("model_list:\n  - model_name: test\n")
        result = watch.validate_config(path)
        os.unlink(path)
        self.assertFalse(result)

    def test_bad_mcp_sse_url_blocks_restart(self):
        path = self._write_config(
            "litellm_settings:\n  mcp_servers:\n    bad-sse:\n      url: ftp://not-valid.com/sse\n"
        )
        result = watch.validate_config(path)
        os.unlink(path)
        self.assertFalse(result)

    def test_bad_mcp_args_type_blocks_restart(self):
        path = self._write_config(
            "litellm_settings:\n  mcp_servers:\n    mcp-bad:\n      command: npx\n      args: not-a-list\n"
        )
        result = watch.validate_config(path)
        os.unlink(path)
        self.assertFalse(result)

    def test_file_not_found(self):
        result = watch.validate_config("/tmp/does-not-exist-xyzabc.yaml")
        self.assertFalse(result)

    def test_empty_yaml_is_invalid(self):
        path = self._write_config("")
        result = watch.validate_config(path)
        os.unlink(path)
        self.assertFalse(result)

    def test_non_mapping_root_is_invalid(self):
        path = self._write_config("- item1\n- item2\n")
        result = watch.validate_config(path)
        os.unlink(path)
        self.assertFalse(result)


if __name__ == "__main__":
    loader = unittest.TestLoader()
    suite = unittest.TestSuite()
    suite.addTests(loader.loadTestsFromTestCase(TestValidateModelList))
    suite.addTests(loader.loadTestsFromTestCase(TestValidateMcpServers))
    suite.addTests(loader.loadTestsFromTestCase(TestValidateConfig))

    runner = unittest.TextTestRunner(verbosity=2, stream=sys.stdout)
    result = runner.run(suite)
    sys.exit(0 if result.wasSuccessful() else 1)
