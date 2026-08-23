import importlib.util
import json
import sys
from pathlib import Path

import pytest

from les_cloches.core.platforms import PlatformSupport

pytestmark = pytest.mark.medium


def _load_commissioning_module(monkeypatch, script_name):
    commissioning = Path(__file__).parents[1] / "commissioning"
    monkeypatch.syspath_prepend(str(commissioning))
    path = commissioning / script_name
    spec = importlib.util.spec_from_file_location(path.stem, path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    monkeypatch.setitem(sys.modules, path.stem, module)
    spec.loader.exec_module(module)
    return module


@pytest.mark.parametrize(
    "script_name",
    [
        "commission_claude_x11.py",
        "commission_chatgpt_x11.py",
    ],
)
def test_commission_send_forwards_restart_permission(monkeypatch, script_name):
    module = _load_commissioning_module(monkeypatch, script_name)
    captured = {}

    def fake_send(*args, **kwargs):
        captured["args"] = args
        captured["kwargs"] = kwargs
        return "ok"

    monkeypatch.setattr(module.lc_transport, "send", fake_send)
    commission = module.Commission.__new__(module.Commission)
    commission.adapter = object()
    commission.input_backend = object()
    commission.timeout = 12.0
    commission.allow_restart_existing_session = True

    assert commission.send("hello") == "ok"
    assert captured["kwargs"]["allow_restart_existing_session"] is True


@pytest.mark.parametrize(
    ("script_name", "adapter_name", "identity", "sentinel_prefix", "output_name"),
    [
        (
            "commission_claude_windows.py",
            "WindowsClaudeAdapter",
            "New chat",
            "WINDOWS_CLAUDE_PONG",
            "WINDOWS_CLAUDE_COMMISSIONING.json",
        ),
        (
            "commission_chatgpt_windows.py",
            "ProjectChatGPTAdapter",
            "Project les-cloches / New chat",
            "WINDOWS_CHATGPT_PONG",
            "WINDOWS_CHATGPT_COMMISSIONING.json",
        ),
    ],
)
def test_windows_commissioning_scripts_are_app_specific(
    monkeypatch,
    script_name,
    adapter_name,
    identity,
    sentinel_prefix,
    output_name,
):
    module = _load_commissioning_module(monkeypatch, script_name)
    captured = {}

    def fake_run(**kwargs):
        captured.update(kwargs)
        return 0

    monkeypatch.setattr(module, "run_windows_commissioning", fake_run)

    assert module.main([]) == 0
    assert captured["adapter_factory"].__name__ == adapter_name
    assert captured["identity"] == identity
    assert captured["sentinel_prefix"] == sentinel_prefix
    assert captured["output"].name == output_name
    assert not hasattr(module._parser().parse_args([]), "app")


def test_chatgpt_windows_commissioning_opens_a_fresh_project_chat(monkeypatch):
    module = _load_commissioning_module(monkeypatch, "commission_chatgpt_windows.py")
    captured = {}

    def fake_open(adapter, project, deadline):
        captured.update(project=project, deadline=deadline)
        return "editor"

    monkeypatch.setattr(module.WindowsChatGPTAdapter, "open_project_fresh_conversation", fake_open)

    adapter = module.ProjectChatGPTAdapter()
    assert adapter.open_fresh_conversation(42.0) == "editor"
    assert captured == {"project": "les-cloches", "deadline": 42.0}


def test_windows_commissioning_persists_one_app_record(monkeypatch, tmp_path):
    module = _load_commissioning_module(monkeypatch, "_windows_common.py")
    output = tmp_path / "evidence.json"

    class FakeAdapter:
        desktop_label = "Fake Desktop"

    def fake_send(_adapter, _input_backend, prompt, _timeout, **_kwargs):
        return prompt.removeprefix("Reply with exactly: ")

    monkeypatch.setattr(
        module,
        "current_platform_support",
        lambda: PlatformSupport("Windows 11", True, False, False, "test"),
    )
    monkeypatch.setattr(module.transport, "send", fake_send)

    assert module.run_windows_commissioning(
        adapter_factory=FakeAdapter,
        identity="New chat",
        sentinel_prefix="WINDOWS_FAKE_PONG",
        timeout=12.0,
        output=output,
    ) == 0

    evidence = json.loads(output.read_text(encoding="utf-8"))
    assert evidence["pass"] is True
    assert len(evidence["results"]) == 1
    assert evidence["results"][0]["app"] == "Fake Desktop"
    assert evidence["results"][0]["identity"] == "New chat"
