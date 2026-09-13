"""Tests for the resumed-session recap.

A resumed tab is created empty. Nothing on screen said which conversation it
was or whether the resume had connected at all, so a working resume and a
broken one looked identical.
"""
import json
import os
import tempfile
import unittest

from tests.plugin_pkg import load

state = load("session_state")
core = load("session_core")

SM = state.StateManager


def entry(etype, text, ts="2026-09-13T07:01:29Z", **extra):
    row = {"type": etype, "timestamp": ts,
           "message": {"content": [{"type": "text", "text": text}]}}
    row.update(extra)
    return row


def write_jsonl(rows):
    fd, path = tempfile.mkstemp(suffix=".jsonl")
    with os.fdopen(fd, "w") as f:
        for row in rows:
            f.write(json.dumps(row) + "\n")
    return path


def manager_for(path):
    m = SM.__new__(SM)
    m.find_jsonl_path = lambda: path
    return m


# a real prompt as stored: smart-context blocks first, the typed words last
CONTEXT_PROMPT = (
    "[cursor] Current scope: foo (line 1)\n\n"
    "[recently_modified] File: ~/proj/routes/console.php\n"
    "```\nSchedule::command('x')->daily();\n```\n\n"
    "Reply with exactly: MARKER"
)


class StripContextPreambleTest(unittest.TestCase):
    def test_keeps_only_what_the_user_typed(self):
        self.assertEqual(SM.strip_context_preamble(CONTEXT_PROMPT),
                         "Reply with exactly: MARKER")

    def test_plain_prompt_is_untouched(self):
        self.assertEqual(SM.strip_context_preamble("just a question"),
                         "just a question")

    def test_prompt_that_merely_starts_with_a_bracket(self):
        self.assertEqual(SM.strip_context_preamble("[note] my own bracket"),
                         "[note] my own bracket")

    def test_context_block_with_no_closing_fence(self):
        text = "[cursor] Current scope: foo\n\nwhat now?"
        self.assertEqual(SM.strip_context_preamble(text), text.strip())

    def test_empty(self):
        self.assertEqual(SM.strip_context_preamble(""), "")


class RecapTest(unittest.TestCase):
    def setUp(self):
        self.path = write_jsonl([
            entry("user", CONTEXT_PROMPT),
            entry("assistant", "", thinking=True),
            entry("assistant", "MARKER"),
            entry("user", "and what was it again?", ts="2026-09-13T07:02:30Z"),
            entry("assistant", "MARKER", ts="2026-09-13T07:02:34Z"),
        ])
        self.addCleanup(os.unlink, self.path)

    def _recap(self, **kw):
        return manager_for(self.path).recap(**kw)

    def test_counts_real_turns(self):
        self.assertEqual(self._recap()["turns"], 2)

    def test_prompts_are_stripped_of_context(self):
        self.assertEqual(self._recap()["exchanges"][0]["prompt"],
                         "Reply with exactly: MARKER")

    def test_replies_are_paired_with_their_prompt(self):
        self.assertEqual(self._recap()["exchanges"][0]["reply"], "MARKER")

    def test_last_active_is_the_final_timestamp(self):
        self.assertEqual(self._recap()["last_active"], "2026-09-13 07:02:34")

    def test_only_the_last_turns_are_kept(self):
        got = self._recap(max_turns=1)["exchanges"]
        self.assertEqual(len(got), 1)
        self.assertEqual(got[0]["prompt"], "and what was it again?")

    def test_long_text_is_bounded(self):
        path = write_jsonl([entry("user", "x" * 900), entry("assistant", "y" * 900)])
        self.addCleanup(os.unlink, path)
        got = manager_for(path).recap(max_chars=50)["exchanges"][0]
        self.assertEqual(len(got["prompt"]), 50)
        self.assertEqual(len(got["reply"]), 50)

    def test_sidechain_and_meta_rows_are_skipped(self):
        path = write_jsonl([
            entry("user", "real one"),
            entry("user", "agent chatter", isSidechain=True),
            entry("user", "bookkeeping", isMeta=True),
        ])
        self.addCleanup(os.unlink, path)
        self.assertEqual(manager_for(path).recap()["turns"], 1)

    def test_synthetic_turns_are_skipped(self):
        """Wake-ups and retain injections are not things the user said."""
        path = write_jsonl([
            entry("user", "real one"),
            entry("user", "<task-notification>done</task-notification>"),
            entry("user", "[Request interrupted by user]"),
        ])
        self.addCleanup(os.unlink, path)
        self.assertEqual(manager_for(path).recap()["turns"], 1)

    def test_thinking_blocks_are_not_treated_as_a_reply(self):
        path = write_jsonl([
            entry("user", "q"),
            {"type": "assistant", "timestamp": "2026-09-13T07:00:00Z",
             "message": {"content": [{"type": "thinking", "thinking": "hmm"}]}},
            entry("assistant", "the answer"),
        ])
        self.addCleanup(os.unlink, path)
        self.assertEqual(manager_for(path).recap()["exchanges"][0]["reply"], "the answer")

    def test_malformed_line_does_not_abort_the_read(self):
        fd, path = tempfile.mkstemp(suffix=".jsonl")
        with os.fdopen(fd, "w") as f:
            f.write("{not json\n")
            f.write(json.dumps(entry("user", "still counted")) + "\n")
        self.addCleanup(os.unlink, path)
        self.assertEqual(manager_for(path).recap()["turns"], 1)

    def test_no_transcript_yields_nothing(self):
        m = SM.__new__(SM)
        m.find_jsonl_path = lambda: None
        self.assertEqual(m.recap(), {})

    def test_unreadable_transcript_yields_nothing(self):
        self.assertEqual(manager_for("/nope/missing.jsonl").recap(), {})


class OneLineTest(unittest.TestCase):
    def test_newlines_are_flattened(self):
        self.assertEqual(core._one_line("a\n\nb   c"), "a b c")

    def test_long_text_is_truncated_with_an_ellipsis(self):
        got = core._one_line("x" * 300, limit=10)
        self.assertTrue(got.endswith("…"))
        self.assertEqual(len(got), 11)

    def test_short_text_is_untouched(self):
        self.assertEqual(core._one_line("short"), "short")

    def test_empty(self):
        self.assertEqual(core._one_line(""), "")


if __name__ == "__main__":
    unittest.main()
