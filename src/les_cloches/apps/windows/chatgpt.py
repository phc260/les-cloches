"""ChatGPT Desktop semantics for the Windows Microsoft UI Automation tree."""

from __future__ import annotations

import subprocess
import time

from ...accessibility.uia import (
    class_name,
    control_type,
    editable_text,
    find_all,
    find_window,
    focus,
    invoke,
    is_editable,
    name,
    process_id,
    walk,
)
from ...core.deadlines import wait_for
from ...core.errors import LesClochesError, LesClochesTimeout
from ...core.recovery import HealthSnapshot, RendererHealth
from ...core.session import SessionState, terminate_owned_or_existing
from ...core.windows import launch_packaged_with_accessibility, process_ids_for_executable
from ...transport import TransactionState, wait_for_completion


class WindowsChatGPTAdapter:
    """Application-owned ChatGPT semantics over Windows UI Automation."""

    desktop_label = "ChatGPT Desktop"
    window_title = "ChatGPT"
    executable_name = "ChatGPT.exe"
    aumid = "OpenAI.Codex_2p2nqsd0c76g0!App"
    editor_names = ("Message ChatGPT", "Work with ChatGPT")
    user_heading = "You said:"
    assistant_heading = "ChatGPT said:"

    def __init__(self, poll_interval: float = 1.0) -> None:
        self.poll_interval = poll_interval
        self._owned_process: "subprocess.Popen | None" = None

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

    def _is_editor(self, node) -> bool:
        return is_editable(node) and name(node) in self.editor_names

    @staticmethod
    def _is_send(node) -> bool:
        value = name(node)
        return control_type(node) == "Button" and (
            value in {"Send", "Send message", "Submit"} or value.casefold().startswith("send ")
        )

    @staticmethod
    def _is_generating(node) -> bool:
        value = name(node).casefold()
        return control_type(node) == "Button" and "stop" in value and any(
            word in value for word in ("generat", "stream", "response")
        )

    def _is_role_boundary(self, node) -> bool:
        node_type = control_type(node)
        node_name = name(node)
        if node_name not in {self.user_heading, self.assistant_heading}:
            return False
        if node_type == "Heading":
            return True
        return node_type == "Text" and any(
            control_type(child) == "Text" and name(child) == node_name
            for child in node.children()
        )

    @staticmethod
    def _project_key(value: str) -> str:
        return " ".join(value.replace("-", " ").split()).casefold()

    def health_snapshot(self) -> HealthSnapshot:
        window = self._window()
        if window is None:
            process_found = self.existing_process_id() is not None
            health = RendererHealth.FRAME_ONLY if process_found else RendererHealth.PROCESS_ABSENT
            return HealthSnapshot(health, process_found, False, False, False, False, False, 0)
        nodes = list(walk(window))
        documents = [node for node in nodes if control_type(node) == "Document"]
        fresh_found = any(
            control_type(node) == "Button" and name(node) == "New chat" for node in nodes
        )
        expand_found = any(
            control_type(node) == "Button" and name(node) in {"Show sidebar", "Hide sidebar"}
            for node in nodes
        )
        editor_found = any(self._is_editor(node) for node in nodes)
        submit_found = any(self._is_send(node) for node in nodes)
        turns = sum(
            self._is_role_boundary(node) and name(node) == self.assistant_heading for node in nodes
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

    def open_fresh_conversation(self, deadline: float):
        def open_new():
            buttons = self._find_all(
                lambda node: control_type(node) == "Button" and name(node) == "New chat"
            )
            for button in buttons:
                if invoke(button):
                    return True
            return None

        wait_for(deadline, "an actionable ChatGPT New chat button", open_new, poll_interval=self.poll_interval)

        def fresh_editor():
            nodes = list(walk(self._window())) if self._window() is not None else []
            editors = [node for node in nodes if self._is_editor(node)]
            boundaries = [node for node in nodes if self._is_role_boundary(node)]
            return editors[-1] if editors and not boundaries else None

        return wait_for(deadline, "a fresh ChatGPT prompt editor", fresh_editor, poll_interval=self.poll_interval)

    def open_project_fresh_conversation(self, project: str, deadline: float):
        """Commissioning-only entry point that opens New chat inside a project."""
        candidates = self._find_all(
            lambda node: control_type(node) == "Button"
            and self._project_key(name(node)) == self._project_key(project)
            and "folder-row" in class_name(node)
        )
        if not candidates or not invoke(candidates[0]):
            raise LesClochesError(f"could not invoke ChatGPT Project {project!r}")
        wait_for(
            deadline,
            f"ChatGPT Project {project!r}",
            lambda: any(
                control_type(node) == "Text"
                and self._project_key(name(node)) == self._project_key(project)
                for node in walk(self._window())
            ),
            poll_interval=self.poll_interval,
        )
        return self.open_fresh_conversation(deadline)

    def _focus_editor(self, editor, deadline: float):
        candidate = editor
        while time.monotonic() < deadline:
            editors = self._find_all(self._is_editor)
            if editors:
                candidate = editors[-1]
            if focus(candidate):
                return candidate
            time.sleep(min(0.1, max(0.0, deadline - time.monotonic())))
        raise LesClochesTimeout("timed out waiting for semantic focus on ChatGPT's prompt editor")

    def _editor_value(self, editor) -> str:
        values = []
        for node in walk(editor):
            if node is editor or control_type(node) != "Text":
                continue
            if "ProseMirror-trailingBreak" in class_name(node):
                continue
            value = name(node)
            if value not in self.editor_names:
                values.append(value)
        value = "".join(values)
        if value.strip():
            return value
        pattern_value = editable_text(editor)
        for placeholder in self.editor_names:
            pattern_value = pattern_value.replace(placeholder, "")
        return pattern_value.strip("\n")

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
            lambda: next(iter(self._find_all(self._is_send)), None),
            poll_interval=self.poll_interval,
        )
        if not invoke(button):
            raise LesClochesError(f"could not invoke ChatGPT Send button {name(button)!r}")

    def _conversation_stream(self):
        root = self._window()
        if root is None:
            return None
        best = None
        best_count = 0
        for node in walk(root):
            children = node.children()
            count = sum(self._is_role_boundary(child) for child in children)
            if count > best_count:
                best, best_count = node, count
        return best

    def _serialize_chatgpt(self, node) -> str:
        node_type = control_type(node)
        node_name = name(node)
        if self._is_role_boundary(node) or node_type in {"Button", "Image", "StatusBar"}:
            return ""
        children = node.children()
        rendered = "".join(self._serialize_chatgpt(child) for child in children)
        css_class = class_name(node)
        if node_type == "Text":
            return node_name or rendered
        if node_type == "Heading" and node_name:
            return f"## {node_name}\n\n"
        if node_type == "ListItem":
            return "- " + rendered.strip() + "\n"
        if node_type == "List":
            return rendered.rstrip() + "\n\n"
        if "code" in css_class.casefold() and node_name:
            return node_name
        return rendered

    def _assistant_response(self) -> str:
        stream = self._conversation_stream()
        if stream is None:
            return ""
        children = stream.children()
        latest_user = -1
        for index, child in enumerate(children):
            if self._is_role_boundary(child) and name(child) == self.user_heading:
                latest_user = index
        fragments = []
        collecting = False
        for child in children[latest_user + 1 :]:
            if self._is_role_boundary(child):
                heading = name(child)
                if heading == self.user_heading:
                    fragments.clear()
                    collecting = False
                elif heading == self.assistant_heading:
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
        children = stream.children()
        latest_assistant = -1
        for index, child in enumerate(children):
            if self._is_role_boundary(child) and name(child) == self.assistant_heading:
                latest_assistant = index
        return latest_assistant >= 0 and any(
            control_type(child) == "Button"
            and name(child) in {"Copy", "Good response", "Bad response", "Regenerate", "Retry"}
            for child in children[latest_assistant + 1 :]
        )

    def _message_counts(self) -> tuple[int, int]:
        root = self._window()
        user = assistant = 0
        if root is not None:
            for node in walk(root):
                if not self._is_role_boundary(node):
                    continue
                if name(node) == self.user_heading:
                    user += 1
                elif name(node) == self.assistant_heading:
                    assistant += 1
        return user, assistant

    def transaction_state(self) -> TransactionState:
        root = self._window()
        if root is None:
            return TransactionState(False, False, "")
        generating = any(self._is_generating(node) for node in walk(root))
        response = self._assistant_response()
        return TransactionState(generating, bool(response) and not generating and self._assistant_complete(), response)

    def try_stop(self) -> None:
        buttons = self._find_all(self._is_generating)
        if buttons:
            invoke(buttons[-1])

    def send_within_current_conversation(self, input_backend, prompt: str, deadline: float) -> str:
        editor = wait_for(
            deadline,
            "ChatGPT's current prompt editor",
            lambda: next(iter(self._find_all(self._is_editor)), None),
            poll_interval=self.poll_interval,
        )
        before_user, _ = self._message_counts()
        editor = self.insert_prompt(input_backend, editor, prompt, deadline)
        wait_for(
            deadline,
            "the exact prompt in ChatGPT's editor",
            lambda: self.editor_matches(editor, prompt),
            poll_interval=0.1,
        )
        self.submit(editor, deadline)
        response = wait_for_completion(self, deadline)
        after_user, _ = self._message_counts()
        if after_user != before_user + 1:
            raise LesClochesError(
                f"semantic Send created {after_user - before_user} user messages instead of exactly one"
            )
        return response
