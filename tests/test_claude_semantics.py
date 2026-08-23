import pytest

import les_cloches.apps.linux.claude as claude_module
from les_cloches.core.errors import LesClochesError
from les_cloches.apps.linux.claude import ClaudeAdapter

pytestmark = pytest.mark.easy


class Node:
    def __init__(self, role, name="", children=(), attributes=None):
        self.role = role
        self.name = name
        self.children = list(children)
        self.attributes = attributes or {}
        self.parent = None
        for child in self.children:
            child.parent = self

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

    def get_parent(self):
        return self.parent

    def get_text_iface(self):
        # Real AT-SPI nodes always expose this accessor (returning None when
        # there is no text interface); a bare Python double must too, since
        # `safe()` only guards call failures, not missing attributes.
        return None


def adapter():
    return ClaudeAdapter.__new__(ClaudeAdapter)


def article(*content_nodes, heading="Claude responded: to your message"):
    body = Node("group", children=[Node("heading", heading), *content_nodes])
    return Node("article", children=[body])


def test_latest_article_with_claude_heading_owns_the_response():
    a = adapter()
    old = article(Node("static", "old response"))
    new = article(Node("static", "new response"))
    assert a._assistant_response([old, new]) == "new response"


def test_article_without_claude_heading_is_skipped_in_favor_of_an_earlier_one():
    a = adapter()
    claude_turn = article(Node("static", "the response"))
    not_claude = article(Node("static", "not this"), heading="Some other heading")
    # not_claude is the most recent article; the adapter must not treat it as
    # the owned response merely because it is last.
    assert a._assistant_response([claude_turn, not_claude]) == "the response"


def test_bold_and_code_tags_are_serialized_as_markdown():
    a = adapter()
    bold = Node("static", children=[Node("static", "important")], attributes={"tag": "strong"})
    code = Node("static", children=[Node("static", "x = 1")], attributes={"tag": "code"})
    turn = article(bold, Node("static", " "), code)
    assert a._assistant_response([turn]) == "**important** `x = 1`"


def test_empty_article_list_yields_empty_response():
    a = adapter()
    assert a._assistant_response([]) == ""


def test_editor_matches_a_single_static_descendant_carrying_the_whole_prompt():
    # Some editors expose inserted text through a static descendant rather
    # than the entry-level Text interface (get_text_iface is absent here).
    a = adapter()
    editor = Node("entry", children=[Node("static", "hello world")])
    assert a.editor_matches(editor, "hello world") is True


def test_editor_matches_is_false_when_static_fragments_do_not_reassemble_the_prompt():
    a = adapter()
    editor = Node("entry", children=[Node("static", "hello"), Node("static", " world")])
    # Fragments are newline-joined for comparison, not concatenated, so this
    # does not accidentally match a differently-fragmented editor.
    assert a.editor_matches(editor, "hello world") is False


def test_pasted_text_buttons_exclude_the_remove_control():
    pasted = Node("push button", "Pasted Text, pasted, 1 line")
    remove = Node("push button", "Remove Pasted Text, pasted, 1 line")
    root = Node("section", children=[pasted, remove])
    assert ClaudeAdapter._pasted_text_buttons(root) == [pasted]


def test_expanded_paste_matches_only_the_complete_prompt():
    root = Node(
        "section",
        children=[
            Node("static", "Pasted content"),
            Node("static", "the complete prompt"),
        ],
    )
    assert ClaudeAdapter._expanded_paste_matches(root, "the complete prompt") is True
    assert ClaudeAdapter._expanded_paste_matches(root, "the complete promp") is False


def test_expanded_paste_root_is_scoped_to_copy_and_close_controls():
    heading = Node("heading", "Pasted content")
    modal = Node(
        "section",
        children=[
            heading,
            Node("push button", "Copy attachment text"),
            Node("push button", "Close"),
            Node("static", "payload"),
        ],
    )
    app = Node("application", children=[modal])
    a = adapter()
    a._find_all = lambda predicate: [node for node in claude_module.walk(app) if predicate(node)]
    assert a._expanded_paste_root() is modal


def test_insert_prompt_rejects_a_stale_attachment_before_input():
    attachment = Node("push button", "Pasted Text, pasted, 1 line")
    root = Node("section", children=[attachment])
    editor = Node("entry")
    a = adapter()
    a._composer_root = lambda _editor: root

    class InputBackend:
        def replace(self, *_args):
            raise AssertionError("input must not run with stale attachments")

    with pytest.raises(LesClochesError, match="unexpected pasted-text attachments"):
        a.insert_prompt(InputBackend(), editor, "hello", 123.0)


def test_verified_attachment_is_accepted_only_while_it_is_the_sole_payload():
    attachment = Node("push button", "Pasted Text, pasted, 1 line")
    root = Node("section", children=[attachment])
    editor = Node("entry")
    a = adapter()
    a._composer_root = lambda _editor: root
    a._verified_attachment_prompt = "hello"
    assert a.editor_matches(editor, "hello") is True

    root.children.append(Node("push button", "Pasted Text, pasted, 1 line"))
    assert a.editor_matches(editor, "hello") is False


def test_inline_prompt_is_rejected_when_an_attachment_is_also_present():
    attachment = Node("push button", "Pasted Text, pasted, 1 line")
    root = Node("section", children=[attachment])
    editor = Node("entry", children=[Node("static", "hello")])
    a = adapter()
    a._composer_root = lambda _editor: root
    assert a.editor_matches(editor, "hello") is False
