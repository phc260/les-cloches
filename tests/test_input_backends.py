import pytest

import les_cloches.input.x11 as x11_module
from les_cloches.input.x11 import X11ClipboardInput

pytestmark = pytest.mark.easy


def test_x11_backend_resolves_semantic_owner_process():
    class Node:
        def __init__(self, pid=None, parent=None):
            self.pid = pid
            self.parent = parent

        def get_process_id(self):
            return self.pid

        def get_parent(self):
            return self.parent

    app = Node(1234)
    frame = Node(parent=app)
    editor = Node(parent=frame)
    assert X11ClipboardInput._semantic_process_id(editor) == 1234


def test_x11_process_ancestor_lookup_is_bounded_for_missing_process():
    assert X11ClipboardInput._process_ancestors(999_999_999) == [999_999_999]


def test_x11_backend_returns_none_when_no_node_in_the_chain_has_a_pid():
    class Node:
        def __init__(self, parent=None):
            self.parent = parent

        def get_process_id(self):
            return None

        def get_parent(self):
            return self.parent

    editor = Node(parent=Node())
    assert X11ClipboardInput._semantic_process_id(editor) is None


def test_glib_context_drain_stops_at_the_deadline(monkeypatch):
    class Context:
        iterations = 0

        def pending(self):
            return True

        def iteration(self, _may_block):
            self.iterations += 1

    context = Context()
    monkeypatch.setattr(x11_module.time, "monotonic", lambda: 10.0)
    assert X11ClipboardInput._drain_context(context, 9.0) is False
    assert context.iterations == 0


def test_glib_context_drain_processes_finite_ready_work(monkeypatch):
    class Context:
        remaining = 3

        def pending(self):
            return self.remaining > 0

        def iteration(self, _may_block):
            self.remaining -= 1

    context = Context()
    monkeypatch.setattr(x11_module.time, "monotonic", lambda: 1.0)
    assert X11ClipboardInput._drain_context(context, 2.0) is True
    assert context.remaining == 0


def test_x11_source_does_not_drain_glib_between_claiming_clipboard_and_paste():
    """A pre-paste drain can enter an unbounded cold-session GDK callback."""
    from pathlib import Path

    source = Path(x11_module.__file__).read_text(encoding="utf-8")
    claim = source.index("set_clipboard(text)")
    paste = source.index('code("Control_L")', claim)
    assert "_drain_context(context" not in source[claim:paste]
