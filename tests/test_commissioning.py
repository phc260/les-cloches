import importlib.util
import sys
from pathlib import Path

import pytest


@pytest.mark.parametrize(
    "script_name",
    [
        "commission_claude_x11.py",
        "commission_chatgpt_x11.py",
    ],
)
def test_commission_send_forwards_restart_permission(monkeypatch, script_name):
    path = Path(__file__).parents[1] / "commissioning" / script_name
    spec = importlib.util.spec_from_file_location(path.stem, path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    monkeypatch.setitem(sys.modules, path.stem, module)
    spec.loader.exec_module(module)
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
