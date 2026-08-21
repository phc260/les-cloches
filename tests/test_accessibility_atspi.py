from les_cloches.accessibility.atspi import find_all, name, press_named_action, role, safe, walk


class Node:
    def __init__(self, role, name="", children=()):
        self._role = role
        self._name = name
        self.children = list(children)

    def get_role_name(self):
        return self._role

    def get_name(self):
        return self._name

    def get_child_count(self):
        return len(self.children)

    def get_child_at_index(self, index):
        return self.children[index]


class BrokenNode(Node):
    def get_child_count(self):
        raise RuntimeError("stale accessibility proxy")


def test_safe_returns_default_on_exception():
    assert safe(lambda: 1 / 0, "fallback") == "fallback"
    assert safe(lambda: 42) == 42


def test_walk_visits_every_descendant_depth_first():
    tree = Node("frame", children=[Node("entry", "a"), Node("push button", "b")])
    visited = [(role(n), name(n)) for n in walk(tree)]
    assert visited == [("frame", ""), ("entry", "a"), ("push button", "b")]


def test_walk_tolerates_a_stale_node_mid_traversal():
    tree = Node("frame", children=[BrokenNode("entry", "a"), Node("push button", "b")])
    # BrokenNode itself is still yielded; only its children are skipped.
    visited = [(role(n), name(n)) for n in walk(tree)]
    assert ("push button", "b") in visited


def test_find_all_applies_predicate_across_the_tree():
    tree = Node("frame", children=[Node("entry", "a"), Node("push button", "New")])
    buttons = find_all(tree, lambda n: role(n) == "push button")
    assert [name(n) for n in buttons] == ["New"]


def test_find_all_on_missing_root_returns_empty():
    assert find_all(None, lambda n: True) == []


class ActionNode:
    def __init__(self, actions):
        self._actions = actions
        self.invoked = []

    def get_action_iface(self):
        return self

    def get_n_actions(self):
        return len(self._actions)

    def get_action_name(self, index):
        return self._actions[index]

    def do_action(self, index):
        self.invoked.append(index)
        return True


def test_press_named_action_invokes_the_matching_action():
    node = ActionNode(["focus", "press"])
    assert press_named_action(node, {"press", "click"}) is True
    assert node.invoked == [1]


def test_press_named_action_returns_false_without_a_match():
    node = ActionNode(["focus"])
    assert press_named_action(node, {"press", "click"}) is False
