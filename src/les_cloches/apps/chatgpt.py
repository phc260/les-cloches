"""ChatGPT Desktop semantics: the application-owned half of the contract.

ChatGPT Desktop's accessibility tree is flatter than Claude's: there is no
turn-level container node. Turns are delimited by heading text ("You said:" /
"ChatGPT said:") inside one long conversation stream, and the assistant's
owned response is everything between the newest "You said:" heading and the
next user turn. This adapter does not inherit from `apps/claude.py` — the two
trees are materially different shapes, and forcing a shared base class would
either paper over that difference or leave most of the base unused. See
ARCHITECTURE.md.
"""

from __future__ import annotations

import subprocess
import time
from dataclasses import dataclass

from ..accessibility.atspi import (
    attributes,
    find_all,
    name,
    press_named_action,
    require_atspi,
    role,
    safe,
    walk,
)
from ..core.deadlines import wait_for
from ..core.errors import LesClochesError, LesClochesTimeout
from ..core.recovery import HealthSnapshot, RendererHealth
from ..core.session import SessionState, terminate_owned_or_existing
from ..transport import TransactionState, wait_for_completion


@dataclass(frozen=True)
class ChatGPTSemantics:
    """The intentionally small, overridable selector table for this adapter."""

    application_name: str = "Codex"
    frame_name: str = "ChatGPT"
    new_chat_name: str = "New chat"
    sidebar_expand_names: "tuple[str, ...]" = ("Show sidebar", "Expand sidebar")
    editor_names: "tuple[str, ...]" = ("Message ChatGPT", "Work with ChatGPT")
    user_heading: str = "You said:"
    assistant_heading: str = "ChatGPT said:"
    send_names: "tuple[str, ...]" = ("Send", "Send message", "Submit")

    def is_editor(self, atspi, node) -> bool:
        return (
            role(node) == "entry"
            and name(node) in self.editor_names
            and bool(safe(lambda: node.get_state_set().contains(atspi.StateType.EDITABLE), False))
        )

    def is_send(self, node) -> bool:
        node_name = name(node)
        return role(node) == "push button" and (
            node_name in self.send_names or node_name.casefold().startswith("send ")
        )

    def is_generating(self, node) -> bool:
        node_name = name(node).casefold()
        return role(node) in {"push button", "toggle button"} and (
            "stop" in node_name and any(word in node_name for word in ("generat", "stream", "response"))
        )

    def is_role_heading(self, node) -> bool:
        return role(node) == "heading" and name(node) in {self.user_heading, self.assistant_heading}


class ChatGPTAdapter:
    """Application adapter for ChatGPT Desktop on X11."""

    desktop_label = "ChatGPT Desktop"

    def __init__(self, poll_interval: float = 1.0, *, semantics: "ChatGPTSemantics | None" = None) -> None:
        self.Atspi = require_atspi()
        self.poll_interval = poll_interval
        self.semantics = semantics or ChatGPTSemantics()
        self._owned_process: "subprocess.Popen | None" = None

    # -- discovery -----------------------------------------------------

    def _application(self):
        desktop = self.Atspi.get_desktop(0)
        for index in range(desktop.get_child_count()):
            app = desktop.get_child_at_index(index)
            if name(app) != self.semantics.application_name:
                continue
            for child_index in range(safe(app.get_child_count, 0) or 0):
                child = safe(lambda child_index=child_index: app.get_child_at_index(child_index))
                if child is not None and role(child) == "frame" and name(child) == self.semantics.frame_name:
                    return app
        return None

    def _main_frame(self):
        app = self._application()
        if app is None:
            return None
        for index in range(safe(app.get_child_count, 0) or 0):
            child = safe(lambda index=index: app.get_child_at_index(index))
            if child is not None and role(child) == "frame" and name(child) == self.semantics.frame_name:
                return child
        return None

    def existing_process_id(self):
        app = self._application()
        return safe(app.get_process_id) if app is not None else None

    def _find_all(self, predicate):
        return find_all(self._main_frame(), predicate)

    def health_snapshot(self) -> HealthSnapshot:
        app = self._application()
        frame = self._main_frame()
        if app is None or frame is None:
            return HealthSnapshot(RendererHealth.PROCESS_ABSENT, False, False, False, False, False, False, 0)
        nodes = list(walk(frame))
        documents = [node for node in nodes if role(node) in {"document", "document web"}]
        fresh_found = any(role(node) == "push button" and name(node) == self.semantics.new_chat_name for node in nodes)
        sidebar_expand_found = any(
            role(node) == "push button" and name(node) in self.semantics.sidebar_expand_names for node in nodes
        )
        editor_found = any(self.semantics.is_editor(self.Atspi, node) for node in nodes)
        submit_found = any(self.semantics.is_send(node) for node in nodes)
        turns = sum(role(node) == "heading" and name(node) == self.semantics.assistant_heading for node in nodes)
        if not documents:
            health = RendererHealth.FRAME_ONLY
        elif not ((fresh_found or sidebar_expand_found) and editor_found):
            health = RendererHealth.DOCUMENT_LOADING
        else:
            health = RendererHealth.READY
        return HealthSnapshot(health, True, True, bool(documents), fresh_found, editor_found, submit_found, turns)

    # -- lifecycle -------------------------------------------------------

    def launch(self) -> None:
        self._owned_process = subprocess.Popen(
            ["chatgpt", "--force-renderer-accessibility"],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            start_new_session=True,
        )

    def terminate_for_recovery(self, session: SessionState, deadline: float) -> None:
        terminate_owned_or_existing(self._owned_process, session, deadline, self.desktop_label)

    # -- conversation lifecycle ------------------------------------------

    def open_fresh_conversation(self, deadline: float):
        def open_new():
            buttons = self._find_all(
                lambda node: role(node) == "push button" and name(node) == self.semantics.new_chat_name
            )
            for button in buttons:
                if press_named_action(button, {"press", "click"}):
                    return True
            expanders = self._find_all(
                lambda node: role(node) == "push button" and name(node) in self.semantics.sidebar_expand_names
            )
            if expanders:
                press_named_action(expanders[0], {"press", "click"})
            return None

        wait_for(deadline, "an actionable ChatGPT New chat button", open_new, poll_interval=self.poll_interval)

        def fresh_editor():
            editors = self._find_all(lambda node: self.semantics.is_editor(self.Atspi, node))
            role_headings = self._find_all(lambda node: self.semantics.is_role_heading(node))
            return editors[-1] if editors and not role_headings else None

        return wait_for(deadline, "a fresh ChatGPT prompt editor", fresh_editor, poll_interval=self.poll_interval)

    def _focus_editor(self, editor, deadline: float):
        """Focus the current composer, rediscovering it if React replaced the node."""
        candidate = editor
        while time.monotonic() < deadline:
            editors = self._find_all(lambda node: self.semantics.is_editor(self.Atspi, node))
            if editors:
                candidate = editors[-1]
            component = safe(candidate.get_component_iface)
            if component is not None:
                safe(component.grab_focus)
            press_named_action(candidate, {"activate", "focus"})
            if safe(lambda: candidate.get_state_set().contains(self.Atspi.StateType.FOCUSED), False):
                return candidate
            time.sleep(min(0.1, max(0.0, deadline - time.monotonic())))
        raise LesClochesTimeout("timed out waiting for semantic focus on ChatGPT's prompt editor")

    # -- prompt insertion --------------------------------------------------

    def _editor_value(self, editor) -> str:
        """Reconstruct ProseMirror text from editable static descendants.

        ChatGPT's composer does not expose inserted text through the
        entry-level Text interface; the visible text lives in `static`
        descendant nodes instead. This is exactly the application-specific
        semantic reconstruction the shared verification invariant allows.
        """
        values = []
        for node in walk(editor):
            if role(node) != "static":
                continue
            node_name = name(node)
            if node_name in self.semantics.editor_names:
                continue
            values.append(node_name)
        value = "".join(values)
        return value if value.strip() else ""

    def editor_matches(self, editor, prompt: str) -> bool:
        return self._editor_value(editor) == prompt

    def insert_prompt(self, input_backend, editor, prompt: str, deadline: float):
        editor = self._focus_editor(editor, deadline)
        input_backend.replace(editor, prompt, deadline, lambda: self.editor_matches(editor, prompt))
        return editor

    def submit(self, editor, deadline: float) -> None:
        button = wait_for(
            deadline,
            "ChatGPT's enabled Send button",
            lambda: next(iter(self._find_all(lambda node: self.semantics.is_send(node))), None),
            poll_interval=self.poll_interval,
        )
        if not press_named_action(button, {"press", "click"}):
            raise LesClochesError(f"could not invoke ChatGPT Send button {name(button)!r}")

    # -- response ownership and completion ---------------------------------

    def _conversation_stream(self):
        root = self._main_frame()
        if root is None:
            return None
        best = None
        best_count = 0
        for node in walk(root):
            children = [
                safe(lambda index=index: node.get_child_at_index(index))
                for index in range(safe(node.get_child_count, 0) or 0)
            ]
            count = sum(child is not None and self.semantics.is_role_heading(child) for child in children)
            if count > best_count:
                best, best_count = node, count
        return best

    def _code_text(self, node) -> str:
        node_name = name(node)
        if role(node) == "static" and node_name:
            return node_name
        return "".join(
            self._code_text(child)
            for index in range(safe(node.get_child_count, 0) or 0)
            for child in [safe(lambda index=index: node.get_child_at_index(index))]
            if child is not None
        )

    def _serialize_chatgpt(self, node) -> str:
        node_role = role(node)
        node_name = name(node)
        if self.semantics.is_role_heading(node):
            return ""
        if node_role in {"push button", "toggle button", "image", "status bar"}:
            return ""
        children = [
            safe(lambda index=index: node.get_child_at_index(index))
            for index in range(safe(node.get_child_count, 0) or 0)
        ]
        children = [child for child in children if child is not None]
        attrs = attributes(node)
        tag = attrs.get("tag", "")
        css_class = attrs.get("class", "")
        if node_role == "section" and ("CodeBlock" in css_class or "code-snippet" in css_class):
            for descendant in walk(node):
                if attributes(descendant).get("tag") == "code":
                    return self._code_text(descendant)
            return ""
        rendered = "".join(self._serialize_chatgpt(child) for child in children)
        if node_role == "static":
            return node_name or rendered
        if node_role == "heading" and node_name:
            level = int(attrs.get("level", "1") or "1")
            return f"{'#' * max(1, min(level, 6))} {node_name}\n\n"
        if tag == "code" and node_name:
            return node_name
        if node_role == "paragraph" or tag == "p":
            return rendered.rstrip() + "\n\n"
        if node_role == "list item" or tag == "li":
            return "- " + rendered.strip() + "\n"
        if node_role == "list" or tag in {"ul", "ol"}:
            return rendered.rstrip() + "\n\n"
        if tag in {"br", "hr"}:
            return "\n"
        return rendered

    def _assistant_response(self) -> str:
        stream = self._conversation_stream()
        if stream is None:
            return ""
        children = [
            safe(lambda index=index: stream.get_child_at_index(index))
            for index in range(safe(stream.get_child_count, 0) or 0)
        ]
        children = [child for child in children if child is not None]
        latest_user = -1
        for index, child in enumerate(children):
            if role(child) == "heading" and name(child) == self.semantics.user_heading:
                latest_user = index
        fragments: "list[str]" = []
        collecting = False
        for child in children[latest_user + 1 :]:
            if role(child) == "heading":
                heading = name(child)
                if heading == self.semantics.user_heading:
                    fragments.clear()
                    collecting = False
                elif heading == self.semantics.assistant_heading:
                    collecting = True
                elif collecting:
                    fragments.append(self._serialize_chatgpt(child))
            elif collecting:
                fragments.append(self._serialize_chatgpt(child))
        return "".join(fragments).strip()

    def _assistant_complete(self) -> bool:
        stream = self._conversation_stream()
        if stream is None:
            return False
        children = [
            safe(lambda index=index: stream.get_child_at_index(index))
            for index in range(safe(stream.get_child_count, 0) or 0)
        ]
        latest_assistant = -1
        for index, child in enumerate(children):
            if child is not None and role(child) == "heading" and name(child) == self.semantics.assistant_heading:
                latest_assistant = index
        if latest_assistant < 0:
            return False
        return any(
            child is not None
            and role(child) in {"push button", "toggle button"}
            and name(child) in {"Copy", "Good response", "Bad response", "Regenerate"}
            for child in children[latest_assistant + 1 :]
        )

    def _message_counts(self) -> "tuple[int, int]":
        """Commissioning helper: visible user/assistant turn counts."""
        root = self._main_frame()
        user = assistant = 0
        if root is not None:
            for node in walk(root):
                if role(node) != "heading":
                    continue
                if name(node) == self.semantics.user_heading:
                    user += 1
                elif name(node) == self.semantics.assistant_heading:
                    assistant += 1
        return user, assistant

    def transaction_state(self) -> TransactionState:
        root = self._main_frame()
        if root is None:
            return TransactionState(False, False, "")
        generating = any(self.semantics.is_generating(node) for node in walk(root))
        response = self._assistant_response()
        complete = bool(response) and not generating and self._assistant_complete()
        return TransactionState(generating, complete, response)

    def try_stop(self) -> None:
        buttons = self._find_all(lambda node: self.semantics.is_generating(node))
        if buttons:
            press_named_action(buttons[-1], {"press", "click"})

    def send_within_current_conversation(self, input_backend, prompt: str, deadline: float) -> str:
        """Commissioning helper: submit within the currently open conversation
        instead of opening a fresh one, to test multi-turn ownership."""
        editor = wait_for(
            deadline,
            "ChatGPT's current prompt editor",
            lambda: next(iter(self._find_all(lambda node: self.semantics.is_editor(self.Atspi, node))), None),
            poll_interval=self.poll_interval,
        )
        before_user, _ = self._message_counts()
        editor = self.insert_prompt(input_backend, editor, prompt, deadline)
        wait_for(deadline, "the exact prompt in ChatGPT's editor", lambda: self.editor_matches(editor, prompt), poll_interval=0.1)
        self.submit(editor, deadline)
        response = wait_for_completion(self, deadline)
        after_user, _ = self._message_counts()
        if after_user != before_user + 1:
            raise LesClochesError(f"semantic Send created {after_user - before_user} user messages instead of exactly one")
        return response
