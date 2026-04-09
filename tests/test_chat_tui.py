import json
import unittest

from scripts import chat_tui


class FakeResponse:
    def __init__(self, lines):
        self._lines = lines

    def iter_lines(self):
        return iter(self._lines)


class ChatTuiTests(unittest.TestCase):
    def test_build_request_keeps_thinking_enabled_without_completion_cap(self):
        state = chat_tui.ChatState(
            endpoint="http://127.0.0.1:8091",
            model="qwen-3.5-abl",
            system_prompt="system",
            temperature=None,
            top_p=None,
            top_k=None,
            repeat_penalty=None,
            presence_penalty=None,
            thinking_budget=1000,
            messages=[{"role": "system", "content": "system"}, {"role": "user", "content": "hi"}],
        )

        payload = chat_tui.build_request(state)

        self.assertTrue(payload["chat_template_kwargs"]["enable_thinking"])
        self.assertNotIn("max_tokens", payload)
        self.assertEqual(payload["thinking_budget_tokens"], 1000)

    def test_iter_sse_events_yields_json_chunks_and_stops_at_done(self):
        first = {"choices": [{"delta": {"reasoning_content": "Thinking"}}]}
        second = {"choices": [{"delta": {"content": "ok"}}]}
        response = FakeResponse(
            [
                f"data: {json.dumps(first)}",
                "",
                f"data: {json.dumps(second)}",
                "data: [DONE]",
                "data: {\"ignored\": true}",
            ]
        )

        events = list(chat_tui.iter_sse_events(response))

        self.assertEqual(events, [first, second])

    def test_wrap_text_preserves_blank_lines(self):
        wrapped = chat_tui.wrap_text("a\n\nb", width=10)
        self.assertEqual(wrapped, ["a", "", "b"])

    def test_handle_keypress_sends_on_enter_and_uses_ctrl_n_for_newline(self):
        state = chat_tui.ChatState(
            endpoint="http://127.0.0.1:8091",
            model="qwen-3.5-abl",
            system_prompt="system",
            temperature=None,
            top_p=None,
            top_k=None,
            repeat_penalty=None,
            presence_penalty=None,
            thinking_budget=1000,
        )
        state.input_lines = ["hello"]

        self.assertIsNone(chat_tui.handle_keypress(chat_tui.CTRL_N, state))
        self.assertEqual(state.input_lines, ["hello", ""])

        state.input_lines[-1] = "world"
        prompt = chat_tui.handle_keypress(10, state)

        self.assertEqual(prompt, "hello\nworld")
        self.assertEqual(state.input_lines, [""])


if __name__ == "__main__":
    unittest.main()
