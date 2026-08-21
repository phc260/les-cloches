"""Claude Desktop semantics: the application-owned half of the contract.

Claude Desktop's accessibility tree uses turn-level semantic structures —
each exchange is an `article` node, and a fresh conversation is one with no
articles yet. The assistant's owned response is the content of the last
article whose body starts with a heading named "Claude responded:". None of
this generalizes to ChatGPT's flatter turn model; see `apps/chatgpt.py`,
which owns its own, independent selectors.
"""

from __future__ import annotations

import subprocess

from ..accessibility.atspi import (
    find_all,
    is_editable_entry,
    name,
    press_named_action,
    require_atspi,
    role,
    safe,
    text,
    walk,
)
from ..core.deadlines import wait_for
from ..core.errors import LesClochesError
from ..core.recovery import HealthSnapshot, RendererHealth
from ..core.session import SessionState, terminate_owned_or_existing
from ..transport import TransactionState


class ClaudeAdapter:
    """Application adapter for Claude Desktop on X11."""

    desktop_label = "Claude Desktop"

    def __init__(self, poll_interval: float = 1.0) -> None:
        self.Atspi = require_atspi()
        self.poll_interval = poll_interval
        self._owned_process: "subprocess.Popen | None" = None
        self._response_root_node = None
        self._verified_attachment_prompt: "str | None" = None

    # -- discovery -----------------------------------------------------

    def _application(self):
        desktop = self.Atspi.get_desktop(0)
        for index in range(desktop.get_child_count()):
            app = desktop.get_child_at_index(index)
            if "claude" in (safe(app.get_name, "") or "").casefold():
                return app
        return None

    def existing_process_id(self):
        app = self._application()
        return safe(app.get_process_id) if app is not None else None

    def health_snapshot(self) -> HealthSnapshot:
        app = self._application()
        if app is None:
            return HealthSnapshot(RendererHealth.PROCESS_ABSENT, False, False, False, False, False, False, 0)
        nodes = list(walk(app))
        frames = [n for n in nodes if role(n) == "frame"]
        documents = [n for n in nodes if role(n) in {"document", "document web"}]
        fresh_found = any(role(n) == "push button" and name(n) == "New" for n in nodes)
        sidebar_expand_found = any(role(n) == "push button" and name(n) == "Expand sidebar" for n in nodes)
        editor_found = any(is_editable_entry(self.Atspi, n) for n in nodes)
        submit_found = any(
            role(n) == "push button" and any(word in name(n).casefold() for word in ("send", "submit"))
            for n in nodes
        )
        turns = sum(role(n) == "article" for n in nodes)
        if not documents:
            health = RendererHealth.FRAME_ONLY
        elif not ((fresh_found or sidebar_expand_found) and editor_found):
            health = RendererHealth.DOCUMENT_LOADING
        else:
            health = RendererHealth.READY
        return HealthSnapshot(health, True, bool(frames), bool(documents), fresh_found, editor_found, submit_found, turns)

    # -- lifecycle -------------------------------------------------------

    def launch(self) -> None:
        self._owned_process = subprocess.Popen(
            ["claude-desktop", "--force-renderer-accessibility"],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            start_new_session=True,
        )

    def terminate_for_recovery(self, session: SessionState, deadline: float) -> None:
        terminate_owned_or_existing(self._owned_process, session, deadline, self.desktop_label)

    # -- conversation lifecycle ------------------------------------------

    def _find_all(self, predicate):
        return find_all(self._application(), predicate)

    def open_fresh_conversation(self, deadline: float):
        self._verified_attachment_prompt = None

        def fresh_button():
            buttons = self._find_all(lambda n: role(n) == "push button" and name(n) == "New")
            if buttons:
                return buttons[0]
            expanders = self._find_all(lambda n: role(n) == "push button" and name(n) == "Expand sidebar")
            if expanders:
                press_named_action(expanders[0], {"press", "click"})
            return None

        button = wait_for(deadline, "Claude's New conversation button", fresh_button, poll_interval=self.poll_interval)
        if not press_named_action(button, {"press", "click"}):
            raise LesClochesError("could not invoke Claude's New conversation button")

        def editor():
            app = self._application()
            if app is None:
                return None
            editors = []
            article_count = 0
            for node in walk(app):
                if role(node) == "article":
                    article_count += 1
                elif is_editable_entry(self.Atspi, node):
                    editors.append(node)
            if article_count or not editors:
                return None
            return editors[-1]

        chosen = wait_for(deadline, "a fresh Claude prompt editor", editor, poll_interval=self.poll_interval)
        self._response_root_node = self._response_root(chosen)
        return chosen

    def _response_root(self, editor):
        node = editor
        document = None
        for _ in range(30):
            parent = safe(node.get_parent)
            if parent is None:
                break
            node = parent
            node_role = role(node)
            if node_role == "landmark" and name(node) == "Primary pane":
                return node
            if node_role in {"document", "document web"}:
                document = node
        return document

    # -- prompt insertion --------------------------------------------------

    @staticmethod
    def _pasted_text_buttons(root) -> list:
        if root is None:
            return []
        return [
            node
            for node in walk(root)
            if role(node) == "push button" and name(node).startswith("Pasted Text")
        ]

    def _composer_root(self, editor):
        return self._response_root(editor)

    def _expanded_paste_root(self):
        """Return the smallest subtree containing Claude's pasted-content viewer."""
        headings = self._find_all(
            lambda node: role(node) == "heading" and name(node) == "Pasted content"
        )
        if not headings:
            return None
        node = headings[-1]
        for _ in range(12):
            parent = safe(node.get_parent)
            if parent is None:
                break
            node = parent
            descendants = list(walk(node))
            has_copy = any(
                role(candidate) == "push button"
                and name(candidate) == "Copy attachment text"
                for candidate in descendants
            )
            has_close = any(
                role(candidate) == "push button" and name(candidate) == "Close"
                for candidate in descendants
            )
            if has_copy and has_close:
                return node
        return None

    @staticmethod
    def _expanded_paste_matches(root, prompt: str) -> bool:
        if root is None:
            return False
        static_names = [name(node) for node in walk(root) if role(node) == "static"]
        return prompt in static_names or "\n".join(static_names) == prompt

    def _close_expanded_paste(self, root) -> None:
        buttons = [
            node
            for node in walk(root)
            if role(node) == "push button" and name(node) == "Close"
        ]
        if not buttons or not press_named_action(buttons[-1], {"press", "click"}):
            raise LesClochesError("could not close Claude's pasted-content viewer")

    def _verify_pasted_prompt(self, editor, prompt: str, deadline: float) -> bool:
        root = self._composer_root(editor)
        attachments = self._pasted_text_buttons(root)
        if not attachments:
            return False
        if len(attachments) != 1:
            raise LesClochesError(
                f"Claude's composer contains {len(attachments)} pasted-text attachments; expected exactly one"
            )
        if text(editor) not in {None, "", "\n"}:
            raise LesClochesError("Claude's composer contains both inline text and a pasted-text attachment")
        if not press_named_action(attachments[0], {"press", "click"}):
            raise LesClochesError("could not open Claude's pasted-text attachment for verification")

        expanded = wait_for(
            deadline,
            "Claude's expanded pasted-content viewer",
            self._expanded_paste_root,
            poll_interval=self.poll_interval,
        )
        matches = self._expanded_paste_matches(expanded, prompt)
        self._close_expanded_paste(expanded)
        if matches:
            self._verified_attachment_prompt = prompt
        return matches

    def _editor_contains(self, editor, prompt: str) -> bool:
        if (text(editor) or "") == prompt:
            return True
        static_names = [name(node) for node in walk(editor) if role(node) == "static"]
        return prompt in static_names or "\n".join(static_names) == prompt

    def editor_matches(self, editor, prompt: str) -> bool:
        if self._editor_contains(editor, prompt):
            return not self._pasted_text_buttons(self._composer_root(editor))
        if getattr(self, "_verified_attachment_prompt", None) != prompt:
            return False
        attachments = self._pasted_text_buttons(self._composer_root(editor))
        return len(attachments) == 1 and text(editor) in {None, "", "\n"}

    def insert_prompt(self, input_backend, editor, prompt: str, deadline: float):
        self._verified_attachment_prompt = None
        stale = self._pasted_text_buttons(self._composer_root(editor))
        if stale:
            raise LesClochesError(
                f"fresh Claude composer contains {len(stale)} unexpected pasted-text attachments"
            )

        def verify() -> bool:
            if self._editor_contains(editor, prompt):
                return not self._pasted_text_buttons(self._composer_root(editor))
            return self._verify_pasted_prompt(editor, prompt, deadline)

        input_backend.replace(editor, prompt, deadline, verify)
        return editor

    def submit(self, editor, deadline: float) -> None:
        def send_button():
            buttons = self._find_all(
                lambda n: role(n) == "push button" and any(word in name(n).casefold() for word in ("send", "submit"))
            )
            return buttons[-1] if buttons else None

        button = wait_for(deadline, "the enabled Send button", send_button, poll_interval=self.poll_interval)
        if not press_named_action(button, {"press", "click"}):
            raise LesClochesError(f"could not invoke Send button {name(button)!r}")

    # -- response ownership and completion ---------------------------------

    def _serialize_content(self, node) -> str:
        children = [safe(lambda i=i: node.get_child_at_index(i)) for i in range(safe(node.get_child_count, 0) or 0)]
        children = [child for child in children if child is not None]
        if role(node) == "static":
            attrs = safe(node.get_attributes, {}) or {}
            tag = attrs.get("tag")
            if tag in {"strong", "b"}:
                return f"**{''.join(self._serialize_content(child) for child in children)}**"
            if tag == "code":
                return f"`{''.join(self._serialize_content(child) for child in children)}`"
            node_name = name(node)
            if node_name:
                return node_name
        return "".join(self._serialize_content(child) for child in children)

    def _assistant_response(self, articles=None) -> str:
        if articles is None:
            articles = self._find_all(lambda n: role(n) == "article")
        for article in reversed(articles):
            children = [
                safe(lambda i=i: article.get_child_at_index(i)) for i in range(safe(article.get_child_count, 0) or 0)
            ]
            body = children[0] if children else None
            if body is None:
                continue
            body_children = [
                safe(lambda i=i: body.get_child_at_index(i)) for i in range(safe(body.get_child_count, 0) or 0)
            ]
            heading = next((n for n in body_children if n and role(n) == "heading"), None)
            if heading is None or not name(heading).startswith("Claude responded:"):
                continue
            content_nodes = [n for n in body_children if n is not None and n is not heading]
            return "".join(self._serialize_content(content) for content in content_nodes).strip()
        return ""

    def transaction_state(self) -> TransactionState:
        root = self._response_root_node or self._application()
        if root is None:
            return TransactionState(False, False, "")
        generating = False
        finished = False
        articles = []
        for node in walk(root):
            node_role = role(node)
            node_name = name(node)
            if node_role == "push button" and any(word in node_name.casefold() for word in ("stop", "generating")):
                generating = True
            elif node_role == "static" and node_name == "Claude finished the response":
                finished = True
            elif node_role == "article":
                articles.append(node)
        response = self._assistant_response(articles)
        return TransactionState(generating, finished, response)

    def try_stop(self) -> None:
        buttons = self._find_all(lambda n: role(n) == "push button" and "stop" in name(n).casefold())
        if buttons:
            press_named_action(buttons[-1], {"press", "click"})
