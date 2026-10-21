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
