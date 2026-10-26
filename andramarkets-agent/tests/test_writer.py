import sys
import types

import pytest

from andra import narrative
from andra.narrative import FIELDS


def reply(text, stop="end_turn"):
    block = types.SimpleNamespace(type="text", text=text)
    return types.SimpleNamespace(content=[block], stop_reason=stop)


FULL = "\n".join(f"==={f}===\nStocks rose 0.58%." for f in FIELDS)
FACTS = {"us_equity": [{"key": "spx", "last": 7757.17, "chg": 0.58}]}


class Client:
    def __init__(self, replies):
        self.replies = list(replies)
        self.messages = self

    def create(self, **kw):
        return self.replies.pop(0)


def run(monkeypatch, replies):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "test")
    monkeypatch.setitem(sys.modules, "anthropic",
                        types.SimpleNamespace(Anthropic=lambda api_key: Client(replies)))
    return narrative.write(FACTS)


def test_truncated_reply_is_retried(monkeypatch):
    note = run(monkeypatch, [reply(FULL[:200], stop="max_tokens"), reply(FULL)])
    assert note.attempts == 2 and note.audit_ok


def test_reply_missing_sections_is_retried(monkeypatch):
    partial = "===headline===\nStocks firm\n===standfirst===\nThe index added 0."
    note = run(monkeypatch, [reply(partial), reply(FULL)])
    assert note.attempts == 2


def test_never_complete_raises_so_the_run_falls_back(monkeypatch):
    with pytest.raises(RuntimeError):
        run(monkeypatch, [reply(FULL[:300], stop="max_tokens")] * 3)


def _with_usage(r, i, o):
    r.usage = types.SimpleNamespace(input_tokens=i, output_tokens=o)
    return r


def test_usage_counts_every_call_including_failed_attempts(monkeypatch):
    note = run(monkeypatch, [_with_usage(reply(FULL[:200], stop="max_tokens"), 1000, 16000),
                             _with_usage(reply(FULL), 1100, 900)])
    assert note.usage["calls"] == 2
    assert note.usage["input_tokens"] == 2100 and note.usage["output_tokens"] == 16900
    assert note.usage["model_seconds"] >= 0


def test_usage_survives_a_writer_that_gives_up(monkeypatch):
    bad = [_with_usage(reply("no tags here"), 10, 5) for _ in range(3)]
    with pytest.raises(RuntimeError) as e:
        run(monkeypatch, bad)
    assert e.value.usage["calls"] == 3 and e.value.usage["output_tokens"] == 15


def test_thinking_disabled_and_a_stripped_key(monkeypatch):
    """CLAUDE.md: thinking explicitly disabled. Without it the model spent the
    whole budget thinking on all three attempts of the 23 Oct 2026 note
    (blocks ['thinking'], stop max_tokens) and the note shipped as tables."""
    seen = {}

    class Recording(Client):
        def create(self, **kw):
            seen.update(kw)
            return super().create(**kw)

    def anthropic(api_key):
        seen["api_key"] = api_key
        return Recording([reply(FULL)])

    monkeypatch.setenv("ANTHROPIC_API_KEY", " sk-test\n")
    monkeypatch.setitem(sys.modules, "anthropic", types.SimpleNamespace(Anthropic=anthropic))
    narrative.write(FACTS)
    assert seen["thinking"] == {"type": "disabled"} and "temperature" not in seen
    assert seen["max_tokens"] == 16000
    assert seen["api_key"] == "sk-test"
