"""Shared test setup: import the plugin without installing it.

The plugin directory is not a valid Python identifier (see the repo name), so
the suite loads ``__init__.py`` by path — exactly what a fresh clone would hit.
"""

from __future__ import annotations

import importlib.util
import sys
import types
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


def load_plugin_module() -> types.ModuleType:
    spec = importlib.util.spec_from_file_location("clearvoice_plugin", ROOT / "__init__.py")
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


@pytest.fixture()
def plugin(monkeypatch, tmp_path):
    """The plugin module with an isolated data directory."""
    monkeypatch.setenv("CLEARVOICE_DATA_DIR", str(tmp_path / "data"))
    from clearvoice_engine import runtime

    runtime.reset_for_tests()
    module = load_plugin_module()
    yield module
    runtime.reset_for_tests()


class FakeCtx:
    """The slice of PluginContext this plugin uses."""

    def __init__(self, config: dict | None = None) -> None:
        self.config = dict(config or {})
        self.tools: dict[str, tuple[dict, object]] = {}
        self.commands: dict[str, object] = {}
        self.skills: list[str] = []
        self.hooks: list[str] = []
        self.capabilities: list[str] = []

    def register_tool(self, name, toolset, schema, handler, **kwargs):
        self.tools[name] = (schema, handler)

    def register_command(self, name, handler, description=""):
        self.commands[name] = handler

    def register_skill(self, *args, **kwargs):
        self.skills.append(args[0] if args else "")

    def register_hook(self, name, fn, **kwargs):
        self.hooks.append(name)

    def get_config(self, key, default=None):
        return self.config.get(key, default)

    def set_config(self, key, value):
        self.config[key] = value


@pytest.fixture()
def fake_ctx():
    return FakeCtx()
