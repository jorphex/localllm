#!/usr/bin/env python3
from __future__ import annotations

import argparse
import curses
import json
import os
import textwrap
from dataclasses import dataclass, field

import httpx


CTRL_L = 12
CTRL_N = 14
CTRL_R = 18
CTRL_U = 21
BACKSPACE_KEYS = {curses.KEY_BACKSPACE, 127, 8}
INPUT_HEIGHT = 6
HEADER_HEIGHT = 2
FOOTER_HEIGHT = 1
DEFAULT_SYSTEM_PROMPT = ""
DEFAULT_THINKING_BUDGET = 500
COLOR_ENABLED = False


@dataclass
class TranscriptEntry:
    role: str
    text: str
    color: int
    label: str


@dataclass
class ChatState:
    endpoint: str
    model: str
    system_prompt: str
    temperature: float | None
    top_p: float | None
    top_k: int | None
    repeat_penalty: float | None
    presence_penalty: float | None
    thinking_budget: int
    api_key: str | None = None
    messages: list[dict] = field(default_factory=list)
    transcript: list[TranscriptEntry] = field(default_factory=list)
    input_lines: list[str] = field(default_factory=lambda: [""])
    status: str = "Enter send, Ctrl-N newline, PgUp/PgDn scroll, Ctrl-R reset, Ctrl-C quit"
    scroll_offset: int = 0

    def reset_conversation(self) -> None:
        self.messages = [{"role": "system", "content": self.system_prompt}]
        self.transcript = []
        self.status = "Conversation reset"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Tiny curses chat client for a local OpenAI-style model.")
    parser.add_argument("--endpoint", default="http://127.0.0.1:8091", help="Base URL for the local model API")
    parser.add_argument("--model", default="", help="Model id to use; defaults to /props model_alias")
    parser.add_argument(
        "--api-key",
        default=os.environ.get("LOCALLLM_CHAT_API_KEY", ""),
        help="Bearer token for authenticated endpoints",
    )
    parser.add_argument("--system", default=DEFAULT_SYSTEM_PROMPT, help="System prompt")
    parser.add_argument("--temp", type=float, default=None, help="Sampling temperature")
    parser.add_argument("--top-p", type=float, default=None, dest="top_p", help="Sampling top_p")
    parser.add_argument("--top-k", type=int, default=None, dest="top_k", help="Sampling top_k")
    parser.add_argument("--repeat", type=float, default=None, dest="repeat_penalty", help="Repeat penalty")
    parser.add_argument("--presence", type=float, default=None, dest="presence_penalty", help="Presence penalty")
    return parser.parse_args()


def request_headers(api_key: str | None) -> dict[str, str]:
    headers: dict[str, str] = {}
    if api_key:
        headers["Authorization"] = f"Bearer {api_key}"
    return headers


def discover_model(endpoint: str, api_key: str | None) -> str:
    props_url = endpoint.rstrip("/") + "/props"
    with httpx.Client(timeout=5.0) as client:
        response = client.get(props_url, headers=request_headers(api_key))
        response.raise_for_status()
        data = response.json()
    model = str(data.get("model_alias") or "").strip()
    if not model:
        raise RuntimeError(f"Could not discover model alias from {props_url}")
    return model


def build_request(state: ChatState) -> dict:
    payload = {
        "model": state.model,
        "messages": state.messages,
        "stream": True,
        "chat_template_kwargs": {"enable_thinking": True},
        "thinking_budget_tokens": state.thinking_budget,
    }
    if state.temperature is not None:
        payload["temperature"] = state.temperature
    if state.top_p is not None:
        payload["top_p"] = state.top_p
    if state.top_k is not None:
        payload["top_k"] = state.top_k
    if state.repeat_penalty is not None:
        payload["repeat_penalty"] = state.repeat_penalty
    if state.presence_penalty is not None:
        payload["presence_penalty"] = state.presence_penalty
    return payload


def iter_sse_events(response: httpx.Response):
    for raw_line in response.iter_lines():
        if not raw_line:
            continue
        line = raw_line.strip()
        if not line.startswith("data:"):
            continue
        data = line[5:].strip()
        if data == "[DONE]":
            return
        yield json.loads(data)


def wrap_text(text: str, width: int) -> list[str]:
    if width <= 1:
        return [text]
    wrapped: list[str] = []
    for raw_line in text.splitlines() or [""]:
        if raw_line == "":
            wrapped.append("")
            continue
        wrapped.extend(
            textwrap.wrap(
                raw_line,
                width=width,
                replace_whitespace=False,
                drop_whitespace=False,
                break_long_words=True,
                break_on_hyphens=False,
            )
            or [""]
        )
    return wrapped


def add_transcript(state: ChatState, role: str, text: str, color: int, label: str) -> int:
    state.transcript.append(TranscriptEntry(role=role, text=text, color=color, label=label))
    return len(state.transcript) - 1


def color_attr(color: int) -> int:
    if not COLOR_ENABLED:
        if color == 1:
            return curses.A_DIM
        return curses.A_NORMAL
    if color == 1:
        return curses.color_pair(2) | curses.A_DIM
    return curses.color_pair(color)


def draw_box(stdscr: curses.window, y: int, x: int, h: int, w: int, color: int) -> None:
    if h < 2 or w < 2:
        return
    attr = color_attr(color)
    stdscr.attron(attr)
    stdscr.addstr(y, x, "┌" + ("─" * (w - 2)) + "┐")
    for row in range(y + 1, y + h - 1):
        stdscr.addstr(row, x, "│")
        stdscr.addstr(row, x + w - 1, "│")
    stdscr.addstr(y + h - 1, x, "└" + ("─" * (w - 2)) + "┘")
    stdscr.attroff(attr)


def render(stdscr: curses.window, state: ChatState) -> None:
    stdscr.erase()
    height, width = stdscr.getmaxyx()
    transcript_height = max(3, height - HEADER_HEIGHT - INPUT_HEIGHT - FOOTER_HEIGHT)
    transcript_width = max(10, width - 4)
    input_y = HEADER_HEIGHT + transcript_height

    title = f" local chat  {state.model}  {state.endpoint} "
    stdscr.attron(curses.color_pair(4))
    stdscr.addstr(0, 0, " " * max(0, width - 1))
    stdscr.addstr(0, 0, title[: max(0, width - 1)])
    stdscr.attroff(curses.color_pair(4))

    status = state.status[: max(0, width - 1)]
    stdscr.attron(curses.color_pair(5))
    stdscr.addstr(1, 0, " " * max(0, width - 1))
    stdscr.addstr(1, 0, status)
    stdscr.attroff(curses.color_pair(5))

    draw_box(stdscr, HEADER_HEIGHT, 0, transcript_height, width, 4)
    lines: list[tuple[str, int]] = []
    for entry in state.transcript:
        lines.append((f"{entry.label}:", entry.color))
        for line in wrap_text(entry.text, transcript_width):
            lines.append((line, entry.color))
        lines.append(("", entry.color))
    if lines and lines[-1][0] == "":
        lines.pop()

    visible_height = max(1, transcript_height - 2)
    max_scroll = max(0, len(lines) - visible_height)
    state.scroll_offset = min(state.scroll_offset, max_scroll)
    start = max(0, len(lines) - visible_height - state.scroll_offset)
    visible_lines = lines[start : start + visible_height]

    row = HEADER_HEIGHT + 1
    for text, color in visible_lines:
        clipped = text[:transcript_width]
        attr = color_attr(color)
        stdscr.attron(attr)
        stdscr.addstr(row, 2, clipped)
        stdscr.attroff(attr)
        row += 1

    draw_box(stdscr, input_y, 0, INPUT_HEIGHT, width, 4)
    stdscr.attron(curses.color_pair(4))
    stdscr.addstr(input_y, 2, " compose ")
    stdscr.attroff(curses.color_pair(4))

    editor_width = max(1, width - 4)
    max_input_lines = max(1, INPUT_HEIGHT - 2)
    shown_lines = state.input_lines[-max_input_lines:]
    for offset, line in enumerate(shown_lines, start=1):
        stdscr.attron(curses.color_pair(6))
        stdscr.addstr(input_y + offset, 2, line[:editor_width])
        stdscr.attroff(curses.color_pair(6))

    cursor_y = input_y + len(shown_lines)
    cursor_x = 2 + min(len(shown_lines[-1]), editor_width - 1)

    footer = "No client context trimming. No thinking budget. Server context still applies."
    footer = (
        f"No client context trimming. Thinking budget {state.thinking_budget}. "
        "Server context still applies."
    )
    stdscr.attron(curses.color_pair(5))
    stdscr.addstr(height - 1, 0, " " * max(0, width - 1))
    stdscr.addstr(height - 1, 0, footer[: max(0, width - 1)])
    stdscr.attroff(curses.color_pair(5))
    stdscr.move(cursor_y, cursor_x)
    stdscr.refresh()


def handle_keypress(key: int, state: ChatState) -> str | None:
    if key in BACKSPACE_KEYS:
        if state.input_lines[-1]:
            state.input_lines[-1] = state.input_lines[-1][:-1]
        elif len(state.input_lines) > 1:
            state.input_lines.pop()
        return None
    if key == curses.KEY_PPAGE:
        state.scroll_offset += 10
        return None
    if key == curses.KEY_NPAGE:
        state.scroll_offset = max(0, state.scroll_offset - 10)
        return None
    if key == CTRL_L:
        state.scroll_offset = 0
        return None
    if key == CTRL_R:
        state.reset_conversation()
        return None
    if key == CTRL_U:
        state.input_lines = [""]
        state.status = "Composer cleared"
        return None
    if key == CTRL_N:
        state.input_lines.append("")
        return None
    if key in {10, 13, curses.KEY_ENTER}:
        prompt = "\n".join(state.input_lines).strip()
        if prompt:
            state.input_lines = [""]
            return prompt
        state.status = "Composer is empty"
        return None
    if 0 <= key <= 255 and chr(key).isprintable():
        state.input_lines[-1] += chr(key)
    return None


def stream_assistant(stdscr: curses.window, state: ChatState) -> None:
    thinking_index = add_transcript(state, "assistant_reasoning", "", 1, "thinking")
    answer_index = add_transcript(state, "assistant", "", 2, "assistant")
    reasoning = ""
    content = ""
    state.status = "Streaming response"
    render(stdscr, state)

    try:
        with httpx.Client(timeout=httpx.Timeout(connect=10.0, read=None, write=30.0, pool=30.0)) as client:
            with client.stream(
                "POST",
                state.endpoint.rstrip("/") + "/v1/chat/completions",
                headers=request_headers(state.api_key),
                json=build_request(state),
            ) as response:
                response.raise_for_status()
                for event in iter_sse_events(response):
                    delta = (event.get("choices") or [{}])[0].get("delta") or {}
                    reasoning_delta = delta.get("reasoning_content") or ""
                    content_delta = delta.get("content") or ""
                    if reasoning_delta:
                        reasoning += reasoning_delta
                        state.transcript[thinking_index].text = reasoning
                    if content_delta:
                        content += content_delta
                        state.transcript[answer_index].text = content
                    render(stdscr, state)
    except Exception as exc:
        state.transcript.pop()
        state.transcript.pop()
        add_transcript(state, "error", f"{type(exc).__name__}: {exc}", 3, "error")
        state.status = "Request failed"
        render(stdscr, state)
        return

    if not reasoning:
        state.transcript.pop(thinking_index)
        answer_index -= 1
    state.messages.append({"role": "assistant", "content": content, "reasoning_content": reasoning})
    state.status = "Response complete"
    state.scroll_offset = 0
    render(stdscr, state)


def run_chat(stdscr: curses.window, state: ChatState) -> None:
    global COLOR_ENABLED
    try:
        curses.curs_set(1)
    except curses.error:
        pass
    try:
        curses.start_color()
        if curses.has_colors():
            try:
                curses.use_default_colors()
            except curses.error:
                pass
            curses.init_pair(1, curses.COLOR_WHITE, -1)
            curses.init_pair(2, curses.COLOR_WHITE, -1)
            curses.init_pair(3, curses.COLOR_RED, -1)
            curses.init_pair(4, curses.COLOR_CYAN, -1)
            curses.init_pair(5, curses.COLOR_BLUE, -1)
            curses.init_pair(6, curses.COLOR_GREEN, -1)
            COLOR_ENABLED = True
    except curses.error:
        COLOR_ENABLED = False
    stdscr.keypad(True)
    state.reset_conversation()

    while True:
        render(stdscr, state)
        key = stdscr.getch()
        prompt = handle_keypress(key, state)
        if prompt is None:
            continue
        add_transcript(state, "user", prompt, 6, "you")
        state.messages.append({"role": "user", "content": prompt})
        state.status = "Submitting prompt"
        render(stdscr, state)
        stream_assistant(stdscr, state)


def main() -> None:
    args = parse_args()
    model = args.model or discover_model(args.endpoint, args.api_key or None)
    state = ChatState(
        endpoint=args.endpoint,
        model=model,
        api_key=args.api_key or None,
        system_prompt=args.system,
        temperature=args.temp,
        top_p=args.top_p,
        top_k=args.top_k,
        repeat_penalty=args.repeat_penalty,
        presence_penalty=args.presence_penalty,
        thinking_budget=DEFAULT_THINKING_BUDGET,
    )
    try:
        curses.wrapper(run_chat, state)
    except KeyboardInterrupt:
        return


if __name__ == "__main__":
    main()
