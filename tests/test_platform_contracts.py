import ast
from dataclasses import dataclass
from pathlib import Path

import pytest

from diagnostics.probe_accessibility import NodeLimitReached, summarize_tree
from les_cloches.accessibility import atspi, uia
from les_cloches.core.errors import LesClochesError
from les_cloches.input.windows import WindowsClipboardInput
from les_cloches.input.x11 import X11ClipboardInput

pytestmark = pytest.mark.medium


class AtspiNode:
    def __init__(self, label="", children=(), *, role="panel", process_id=11):
        self.label = label
        self._children = list(children)
        self._role = role
        self._process_id = process_id

    def get_child_count(self):
        return len(self._children)

    def get_child_at_index(self, index):
        return self._children[index]

    def get_name(self):
        return self.label

    def get_role_name(self):
        return self._role

    def get_process_id(self):
        return self._process_id


class UiaInfo:
    def __init__(self, label="", control_type="Group", process_id=22):
        self.name = label
        self.control_type = control_type
        self.class_name = ""
        self.automation_id = ""
        self.process_id = process_id


class UiaNode:
    def __init__(self, label="", children=(), *, control_type="Group", process_id=22):
        self.element_info = UiaInfo(label, control_type, process_id)
        self._children = list(children)

    def children(self):
        return self._children


@dataclass(frozen=True)
class AccessibilityContract:
    label: str
    make_node: object
    walk: object
    find_all: object
    node_name: object


CONTRACTS = (
    AccessibilityContract(
        "linux-x11-atspi",
        AtspiNode,
        atspi.walk,
        atspi.find_all,
        atspi.name,
    ),
    AccessibilityContract(
        "windows-uia",
        UiaNode,
        uia.walk,
        uia.find_all,
        uia.name,
    ),
)


@pytest.mark.parametrize("contract", CONTRACTS, ids=lambda item: item.label)
def test_accessibility_backends_share_bounded_semantic_tree_contract(contract):
    leaf = contract.make_node("send")
    root = contract.make_node("root", [contract.make_node("editor"), leaf])

    assert [contract.node_name(node) for node in contract.walk(root)] == ["root", "editor", "send"]
    assert contract.find_all(root, lambda node: contract.node_name(node) == "send") == [leaf]
    assert contract.find_all(None, lambda _node: True) == []
    with pytest.raises(LesClochesError, match="exceeded 2 nodes"):
        list(contract.walk(root, node_limit=2))


@pytest.mark.parametrize(
    ("root", "children", "kind", "process_id", "expected"),
    [
        (
            AtspiNode("root", [AtspiNode("editor", role="entry")], process_id=11),
            lambda node: [node.get_child_at_index(index) for index in range(node.get_child_count())],
            lambda node: node.get_role_name(),
            lambda node: node.get_process_id(),
            {"panel": 1, "entry": 1},
        ),
        (
            UiaNode("root", [UiaNode("editor", control_type="Edit")], process_id=22),
            lambda node: node.children(),
            lambda node: node.element_info.control_type,
            lambda node: node.element_info.process_id,
            {"Edit": 1, "Group": 1},
        ),
    ],
    ids=("linux-x11-atspi", "windows-uia"),
)
def test_bounded_probe_uses_one_content_free_summary_schema(
    root, children, kind, process_id, expected
):
    result = summarize_tree(
        root,
        children=children,
        kind=kind,
        process_id=process_id,
        max_depth=10,
        node_limit=10,
    )

    assert result == {
        "node_count": 2,
        "max_depth_observed": 1,
        "kinds": expected,
        "root_process_id": process_id(root),
    }
    assert "name" not in result
    assert "text" not in result


def test_bounded_probe_stops_before_an_unbounded_tree_walk():
    root = UiaNode("root", [UiaNode("one"), UiaNode("two")])

    with pytest.raises(NodeLimitReached, match="exceeded 2 nodes"):
        summarize_tree(
            root,
            children=lambda node: node.children(),
            kind=lambda node: node.element_info.control_type,
            process_id=lambda node: node.element_info.process_id,
            max_depth=10,
            node_limit=2,
        )


def test_input_backend_names_make_the_platform_mechanism_explicit():
    assert X11ClipboardInput.name == "x11-clipboard-xtest"
    assert WindowsClipboardInput.name == "windows-uia-clipboard-sendinput"


def test_every_renderer_launcher_forces_accessibility_explicitly():
    root = Path(__file__).parents[1]
    for relative in (
        "src/les_cloches/apps/linux/claude.py",
        "src/les_cloches/apps/linux/chatgpt.py",
        "src/les_cloches/core/windows.py",
    ):
        assert "--force-renderer-accessibility" in (root / relative).read_text(encoding="utf-8")


def test_runtime_does_not_import_forbidden_automation_stacks():
    root = Path(__file__).parents[1] / "src" / "les_cloches"
    forbidden = {
        "cv2",
        "PIL",
        "playwright",
        "pyautogui",
        "pyscreeze",
        "pytesseract",
        "selenium",
        "websocket",
        "websockets",
    }
    violations = []
    for path in root.rglob("*.py"):
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                imported = {alias.name.split(".", 1)[0] for alias in node.names}
            elif isinstance(node, ast.ImportFrom) and node.module:
                imported = {node.module.split(".", 1)[0]}
            else:
                continue
            for name in sorted(imported & forbidden):
                violations.append(f"{path.relative_to(root)} imports {name}")
    assert violations == []
