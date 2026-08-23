import pytest

from les_cloches.accessibility.uia import editable_text, find_all, walk

pytestmark = pytest.mark.easy


class Info:
    def __init__(self, name="", control_type="Group", class_name="", process_id=1):
        self.name = name
        self.control_type = control_type
        self.class_name = class_name
        self.automation_id = ""
        self.process_id = process_id


class Node:
    def __init__(self, name="", control_type="Group", children=(), text=None):
        self.element_info = Info(name, control_type)
        self._children = list(children)
        self._text = text

    def children(self):
        return self._children

    @property
    def iface_text(self):
        value = self._text

        class Range:
            def GetText(self, _length):
                return value

        class Pattern:
            DocumentRange = Range()

        return Pattern()


def test_uia_walk_is_depth_first_and_find_all_is_semantic():
    leaf = Node("send", "Button")
    root = Node(children=[Node("editor", "Edit"), leaf])
    assert [node.element_info.name for node in walk(root)] == ["", "editor", "send"]
    assert find_all(root, lambda node: node.element_info.control_type == "Button") == [leaf]


def test_editable_text_reads_uia_text_pattern_exactly():
    assert editable_text(Node(control_type="Edit", text="a\r\nb")) == "a\r\nb"
