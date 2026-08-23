"""Claude Desktop semantics for the Windows Microsoft UI Automation tree."""

from __future__ import annotations

import re
import subprocess

from ...accessibility.uia import (
    class_name,
    control_type,
    editable_text,
    find_all,
    find_window,
    invoke,
    is_editable,
    name,
    parent,
    process_id,
    walk,
)
from ...core.deadlines import wait_for
from ...core.errors import LesClochesError
from ...core.recovery import HealthSnapshot, RendererHealth
from ...core.session import SessionState, terminate_owned_or_existing
from ...core.windows import launch_packaged_with_accessibility, process_ids_for_executable
from ...transport import TransactionState


class WindowsClaudeAdapter:
    """Application-owned Claude semantics over Windows UI Automation."""

    desktop_label = "Claude Desktop"
    window_title = "Claude"
    executable_name = "Claude.exe"
    aumid = "Claude_pzs8sxrjxfjjc!Claude"

    def __init__(self, poll_interval: float = 1.0) -> None:
        self.poll_interval = poll_interval
        self._owned_process: "subprocess.Popen | None" = None
        self._response_root_node = None
        self._verified_attachment_prompt: "str | None" = None

    def _window(self):
        return find_window(self.window_title)

    def existing_process_id(self):
        window = self._window()
        if window is not None:
            return process_id(window)
        processes = process_ids_for_executable(self.executable_name)
        return processes[0] if processes else None

    def _find_all(self, predicate):
        return find_all(self._window(), predicate)

    @staticmethod
    def _is_editor(node) -> bool:
        return is_editable(node) and name(node) == "Write your prompt to Claude"

    @staticmethod
    def _is_message_group(node) -> bool:
        return control_type(node) == "Group" and re.fullmatch(
            r"Message [0-9]+ of [0-9]+", name(node)
        ) is not None

    @staticmethod
    def _is_user_message(node) -> bool:
        return any(
            control_type(child) == "Text" and name(child).startswith("You said:")
            for child in node.children()
        )

    def health_snapshot(self) -> HealthSnapshot:
        window = self._window()
        if window is None:
            process_found = self.existing_process_id() is not None
            health = RendererHealth.FRAME_ONLY if process_found else RendererHealth.PROCESS_ABSENT
            return HealthSnapshot(health, process_found, False, False, False, False, False, 0)
        nodes = list(walk(window))
        documents = [node for node in nodes if control_type(node) == "Document"]
        fresh_found = any(control_type(node) == "Button" and name(node) == "New" for node in nodes)
        expand_found = any(
            control_type(node) == "Button" and name(node) in {"Expand sidebar", "Menu"}
            for node in nodes
        )
        editor_found = any(self._is_editor(node) for node in nodes)
        submit_found = any(
            control_type(node) == "Button" and name(node).casefold().startswith(("send", "submit"))
            for node in nodes
        )
        turns = sum(
            self._is_message_group(node) and not self._is_user_message(node) for node in nodes
        )
        if not documents:
            health = RendererHealth.FRAME_ONLY
        elif not ((fresh_found or expand_found) and editor_found):
            health = RendererHealth.DOCUMENT_LOADING
        else:
            health = RendererHealth.READY
        return HealthSnapshot(health, True, True, True, fresh_found, editor_found, submit_found, turns)

    def launch(self, deadline: float) -> None:
        self._owned_process = launch_packaged_with_accessibility(
            aumid=self.aumid,
            window_title=self.window_title,
            executable_name=self.executable_name,
            deadline=deadline,
        )

    def terminate_for_recovery(self, session: SessionState, deadline: float) -> None:
        terminate_owned_or_existing(self._owned_process, session, deadline, self.desktop_label)

    def _response_root(self, editor):
        node = editor
        document = None
        for _ in range(40):
            node = parent(node)
            if node is None:
                break
            if control_type(node) == "Group" and name(node) == "Primary pane":
                return node
            if control_type(node) == "Document":
                document = node
        return document

    def open_fresh_conversation(self, deadline: float):
        self._verified_attachment_prompt = None

        def open_new():
            buttons = self._find_all(
                lambda node: control_type(node) == "Button" and name(node) == "New"
            )
            for button in buttons:
                if invoke(button):
                    return True
            expanders = self._find_all(
                lambda node: control_type(node) == "Button"
                and name(node) in {"Expand sidebar", "Menu"}
            )
            if expanders:
                invoke(expanders[0])
            return None

        wait_for(deadline, "Claude's actionable New conversation button", open_new, poll_interval=self.poll_interval)

        def select_chat():
            radios = self._find_all(
                lambda node: control_type(node) == "RadioButton" and name(node) == "Chat"
            )
            if not radios:
                return None
            chat = radios[-1]
            try:
                if bool(chat.iface_selection_item.CurrentIsSelected):
                    return True
            except Exception:
                pass
            invoke(chat)
            return None

        wait_for(deadline, "Claude's Chat surface", select_chat, poll_interval=self.poll_interval)

        def fresh_editor():
            window = self._window()
            if window is None:
                return None
            nodes = list(walk(window))
            editors = [node for node in nodes if self._is_editor(node)]
            messages = [node for node in nodes if self._is_message_group(node)]
            return editors[-1] if editors and not messages else None

        editor = wait_for(deadline, "a fresh Claude prompt editor", fresh_editor, poll_interval=self.poll_interval)
        self._response_root_node = self._response_root(editor)
        return editor

    def _composer_root(self, editor):
        return self._response_root(editor)

    @staticmethod
    def _pasted_text_buttons(root) -> list:
        return [
            node
            for node in walk(root)
            if control_type(node) == "Button" and name(node).startswith("Pasted Text")
        ] if root is not None else []

    @staticmethod
    def _editor_value(editor) -> str:
        values = []
        for node in walk(editor):
            if node is editor or control_type(node) != "Text":
                continue
            if "ProseMirror-trailingBreak" in class_name(node):
                continue
            value = name(node)
            if value and value != "How can I help you today?":
                values.append(value)
        if values:
            return "".join(values)
        value = editable_text(editor)
        return "" if value in {"", "\n", "Write your prompt to Claude"} else value

    def editor_matches(self, editor, prompt: str) -> bool:
        return self._editor_value(editor) == prompt and not self._pasted_text_buttons(self._composer_root(editor))

    def insert_prompt(self, input_backend, editor, prompt: str, deadline: float):
        editors = self._find_all(self._is_editor)
        if editors:
            editor = editors[-1]
        stale = self._pasted_text_buttons(self._composer_root(editor))
        if stale:
            raise LesClochesError(
                f"fresh Claude composer contains {len(stale)} unexpected pasted-text attachments"
            )
        input_backend.replace(editor, prompt, deadline, lambda: self.editor_matches(editor, prompt))
        return editor

    def submit(self, editor, deadline: float) -> None:
        button = wait_for(
            deadline,
            "Claude's enabled Send button",
            lambda: next(
                iter(
                    self._find_all(
                        lambda node: control_type(node) == "Button"
                        and name(node).casefold().startswith(("send", "submit"))
                    )
                ),
                None,
            ),
            poll_interval=self.poll_interval,
        )
        if not invoke(button):
            raise LesClochesError(f"could not invoke Claude Send button {name(button)!r}")

    def _serialize_content(self, node) -> str:
        node_type = control_type(node)
        node_name = name(node)
        if node_type in {"Button", "Image", "StatusBar"}:
            return ""
        children = node.children()
        rendered = "".join(self._serialize_content(child) for child in children)
        css_class = class_name(node)
        if node_type == "Text":
            return node_name or rendered
        if node_type == "Heading" and node_name:
            return f"## {node_name}\n\n"
        if node_type == "ListItem":
            return f"- {rendered.strip()}\n"
        if node_type == "List":
            return rendered.rstrip() + "\n\n"
        if "code" in css_class.casefold() and node_name:
            return node_name
        return rendered

    def _assistant_message(self, nodes=None):
        nodes = list(walk(self._response_root_node or self._window())) if nodes is None else nodes
        users = [
            node for node in nodes if self._is_message_group(node) and self._is_user_message(node)
        ]
        if not users:
            return None
        user = users[-1]
        container = parent(user)
        if container is None:
            return None
        children = container.children()
        try:
            candidate = children[children.index(user) + 1]
            return candidate if self._is_message_group(candidate) and not self._is_user_message(candidate) else None
        except (ValueError, IndexError):
            return None

    def _assistant_response(self, nodes=None) -> str:
        assistant = self._assistant_message(nodes)
        if assistant is None:
            return ""
        content = next(
            (child for child in assistant.children() if control_type(child) == "Group"),
            None,
        )
        if content is not None:
            return self._serialize_content(content).strip()
        return "".join(
            self._serialize_content(child)
            for child in assistant.children()
            if control_type(child) != "ToolBar"
            and not (
                control_type(child) == "Text" and name(child).startswith("Claude responded:")
            )
        ).strip()

    def transaction_state(self) -> TransactionState:
        root = self._response_root_node or self._window()
        if root is None:
            return TransactionState(False, False, "")
        nodes = list(walk(root))
        generating = any(
            control_type(node) == "Button"
            and any(word in name(node).casefold() for word in ("stop", "generating"))
            for node in nodes
        )
        assistant = self._assistant_message(nodes)
        response = self._assistant_response(nodes)
        complete_marker = assistant is not None and any(
            control_type(node) == "Button" and name(node) in {"Copy", "Retry", "Regenerate"}
            for node in walk(assistant)
        )
        return TransactionState(generating, bool(response) and not generating and complete_marker, response)

    def try_stop(self) -> None:
        buttons = self._find_all(
            lambda node: control_type(node) == "Button" and "stop" in name(node).casefold()
        )
        if buttons:
            invoke(buttons[-1])
