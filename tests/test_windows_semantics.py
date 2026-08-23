import time

import pytest

from les_cloches.apps.windows import chatgpt
from les_cloches.apps.windows.chatgpt import WindowsChatGPTAdapter
from les_cloches.apps.windows.claude import WindowsClaudeAdapter
from les_cloches.input.windows import WindowsClipboardInput

pytestmark = pytest.mark.easy


class Info:
    def __init__(self, name="", control_type="Group", class_name=""):
        self.name = name
        self.control_type = control_type
        self.class_name = class_name
        self.automation_id = ""
        self.process_id = 1


class Node:
    def __init__(self, name="", control_type="Group", class_name="", children=()):
        self.element_info = Info(name, control_type, class_name)
        self._children = list(children)
        self._parent = None
        for child in self._children:
            child._parent = self

    def children(self):
        return self._children

    def parent(self):
        return self._parent


def test_chatgpt_editor_reconstruction_excludes_placeholder_and_trailing_break():
    adapter = WindowsChatGPTAdapter()
    editor = Node(
        "Message ChatGPT",
        "Edit",
        children=[
            Node("hello", "Text"),
            Node("\n", "Text", "ProseMirror-trailingBreak"),
            Node("Message ChatGPT", "Text"),
        ],
    )
    assert adapter._editor_value(editor) == "hello"


def test_claude_editor_reconstruction_is_exact():
    adapter = WindowsClaudeAdapter()
    editor = Node(
        "Write your prompt to Claude",
        "Edit",
        children=[Node("alpha", "Text"), Node("beta", "Text")],
    )
    assert adapter._editor_value(editor) == "alphabeta"


def test_claude_reacquires_editor_immediately_before_input(monkeypatch):
    adapter = WindowsClaudeAdapter()
    stale_editor = Node("Write your prompt to Claude", "Edit")
    current_editor = Node("Write your prompt to Claude", "Edit")
    received = []

    class Input:
        def replace(self, editor, prompt, deadline, verify):
            received.append((editor, prompt, deadline, verify()))

    monkeypatch.setattr(adapter, "_find_all", lambda predicate: [current_editor])
    monkeypatch.setattr(adapter, "_composer_root", lambda editor: None)
    monkeypatch.setattr(adapter, "_pasted_text_buttons", lambda root: [])
    monkeypatch.setattr(adapter, "editor_matches", lambda editor, prompt: editor is current_editor)

    assert adapter.insert_prompt(Input(), stale_editor, "exact", 42.0) is current_editor
    assert received == [(current_editor, "exact", 42.0, True)]


def test_chatgpt_project_name_matching_is_case_insensitive(monkeypatch):
    adapter = WindowsChatGPTAdapter()
    project_button = Node("Les Cloches", "Button", "sidebar-item folder-row")
    window = Node(children=[Node("Les Cloches", "Text")])

    monkeypatch.setattr(
        adapter,
        "_find_all",
        lambda predicate: [project_button] if predicate(project_button) else [],
    )
    monkeypatch.setattr(adapter, "_window", lambda: window)
    monkeypatch.setattr(adapter, "open_fresh_conversation", lambda deadline: "editor")
    monkeypatch.setattr(chatgpt, "invoke", lambda node: node is project_button)

    def immediate_wait(deadline, description, predicate, **kwargs):
        assert predicate()
        return True

    monkeypatch.setattr(chatgpt, "wait_for", immediate_wait)

    assert adapter.open_project_fresh_conversation("les-cloches", 42.0) == "editor"


def test_windows_input_prefers_exact_semantic_value_write():
    state = {"value": ""}

    class ValuePattern:
        CurrentIsReadOnly = False

        @staticmethod
        def SetValue(value):
            state["value"] = value

    class Editor:
        iface_value = ValuePattern()

    WindowsClipboardInput().replace(
        Editor(),
        "exact",
        time.monotonic() + 1.0,
        lambda: state["value"] == "exact",
    )
    assert state["value"] == "exact"


def test_claude_windows_response_is_owned_by_latest_message_sibling():
    stale = Node(
        "Message 2 of 2",
        children=[Node(children=[Node("STALE", "Text")]), Node(children=[Node("Copy", "Button")])],
    )
    user = Node("Message 3 of 4", children=[Node("You said: exact", "Text")])
    assistant = Node(
        "Message 4 of 4",
        children=[Node(children=[Node("PONG", "Text")]), Node(children=[Node("Copy", "Button")])],
    )
    root = Node(children=[Node("Message 1 of 2", children=[Node("You said: old", "Text")]), stale, user, assistant])
    adapter = WindowsClaudeAdapter()
    adapter._response_root_node = root

    state = adapter.transaction_state()
    assert state.response == "PONG"
    assert state.complete is True


def test_claude_windows_response_accepts_direct_text_content():
    user = Node("Message 1 of 2", children=[Node("You said: exact", "Text")])
    assistant = Node(
        "Message 2 of 2",
        children=[
            Node("Claude responded: PONG", "Text"),
            Node("PONG", "Text"),
            Node(
                "Message actions",
                "ToolBar",
                children=[Node("just now", "Text"), Node("Copy", "Button")],
            ),
        ],
    )
    adapter = WindowsClaudeAdapter()
    adapter._response_root_node = Node(children=[user, assistant])

    state = adapter.transaction_state()
    assert state.response == "PONG"
    assert state.complete is True


def test_chatgpt_windows_response_uses_outer_text_boundaries(monkeypatch):
    def boundary(value):
        return Node(value, "Text", children=[Node(value, "Text")])

    stream = Node(
        children=[
            boundary("You said:"),
            Node(children=[Node("old prompt", "Text")]),
            boundary("ChatGPT said:"),
            Node(children=[Node("STALE", "Text")]),
            Node("Copy", "Button"),
            boundary("You said:"),
            Node(children=[Node("exact", "Text")]),
            boundary("ChatGPT said:"),
            Node(children=[Node("PONG", "Text")]),
            Node("Copy", "Button"),
        ]
    )
    root = Node(children=[stream])
    adapter = WindowsChatGPTAdapter()
    monkeypatch.setattr(adapter, "_window", lambda: root)

    state = adapter.transaction_state()
    assert state.response == "PONG"
    assert state.complete is True
