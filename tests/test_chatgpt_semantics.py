from les_cloches.apps.chatgpt import ChatGPTAdapter, ChatGPTSemantics


class Node:
    def __init__(self, role, name="", children=(), attributes=None):
        self.role = role
        self.name = name
        self.children = list(children)
        self.attributes = attributes or {}

    def get_role_name(self):
        return self.role

    def get_name(self):
        return self.name

    def get_child_count(self):
        return len(self.children)

    def get_child_at_index(self, index):
        return self.children[index]

    def get_attributes(self):
        return self.attributes


def adapter_with_stream(*children):
    adapter = ChatGPTAdapter.__new__(ChatGPTAdapter)
    adapter.semantics = ChatGPTSemantics()
    adapter._main_frame = lambda: Node("frame", children=[Node("section", children=children)])
    return adapter


def test_response_belongs_to_latest_user_turn():
    adapter = adapter_with_stream(
        Node("heading", "You said:"),
        Node("paragraph", children=[Node("static", "old prompt")], attributes={"tag": "p"}),
        Node("heading", "ChatGPT said:"),
        Node("paragraph", children=[Node("static", "old response")], attributes={"tag": "p"}),
        Node("push button", "Copy"),
        Node("heading", "You said:"),
        Node("paragraph", children=[Node("static", "new prompt")], attributes={"tag": "p"}),
        Node("heading", "ChatGPT said:"),
        Node("paragraph", children=[Node("static", "new response")], attributes={"tag": "p"}),
        Node("push button", "Copy"),
    )
    assert adapter._assistant_response() == "new response"


def test_consecutive_assistant_fragments_are_owned_by_same_invocation():
    adapter = adapter_with_stream(
        Node("heading", "You said:"),
        Node("heading", "ChatGPT said:"),
        Node("paragraph", children=[Node("static", "part one")], attributes={"tag": "p"}),
        Node("heading", "ChatGPT said:"),
        Node("paragraph", children=[Node("static", "part two")], attributes={"tag": "p"}),
        Node("push button", "Copy"),
    )
    assert adapter._assistant_response() == "part one\n\npart two"


def test_message_controls_are_not_extracted():
    adapter = adapter_with_stream(
        Node("heading", "You said:"),
        Node("heading", "ChatGPT said:"),
        Node("paragraph", children=[Node("static", "PONG")], attributes={"tag": "p"}),
        Node("push button", "Copy"),
        Node("toggle button", "Good response"),
        Node("toggle button", "Bad response"),
    )
    assert adapter._assistant_response() == "PONG"
    assert adapter._assistant_complete() is True


def test_markdown_structure_is_serialized_without_ui_labels():
    adapter = adapter_with_stream(
        Node("heading", "You said:"),
        Node("heading", "ChatGPT said:"),
        Node("heading", "Title", children=[Node("static", "Title")], attributes={"level": "2", "tag": "h2"}),
        Node(
            "list",
            children=[
                Node("list item", children=[Node("static", "one")], attributes={"tag": "li"}),
                Node("list item", children=[Node("static", "two")], attributes={"tag": "li"}),
            ],
            attributes={"tag": "ul"},
        ),
        Node("push button", "Copy"),
    )
    assert adapter._assistant_response() == "## Title\n\n- one\n- two"


def test_editor_value_joins_chromium_line_break_static_nodes():
    adapter = ChatGPTAdapter.__new__(ChatGPTAdapter)
    adapter.semantics = ChatGPTSemantics()
    editor = Node(
        "entry",
        "Message ChatGPT",
        children=[Node("paragraph", children=[
            Node("static", "line one"),
            Node("static", "\n"),
            Node("static", "line two"),
        ])],
    )
    assert adapter._editor_value(editor) == "line one\nline two"
    assert adapter.editor_matches(editor, "line one\nline two")


def test_editor_value_ignores_empty_editor_placeholder():
    adapter = ChatGPTAdapter.__new__(ChatGPTAdapter)
    adapter.semantics = ChatGPTSemantics()
    editor = Node(
        "entry",
        "Message ChatGPT",
        children=[Node("paragraph", children=[
            Node("static", "\n"),
            Node("section", children=[Node("static", "Message ChatGPT")]),
        ])],
    )
    assert adapter._editor_value(editor) == ""


def test_code_block_excludes_language_and_copy_controls():
    adapter = adapter_with_stream(
        Node("heading", "You said:"),
        Node("heading", "ChatGPT said:"),
        Node(
            "section",
            children=[
                Node("section", children=[Node("static", "Plain text"), Node("push button", "Copy")]),
                Node(
                    "section",
                    children=[Node("static", children=[Node("static", "smoke_code")], attributes={"tag": "code"})],
                ),
            ],
            attributes={"class": "example _CodeBlock_123", "tag": "div"},
        ),
        Node("push button", "Copy"),
    )
    assert adapter._assistant_response() == "smoke_code"
