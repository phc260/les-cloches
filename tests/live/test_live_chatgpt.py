import json
import os

import pytest

from les_cloches import ChatGPT

pytestmark = pytest.mark.skipif(
    os.environ.get("LES_CLOCHES_LIVE") != "1",
    reason="set LES_CLOCHES_LIVE=1 to control the real ChatGPT Desktop GUI",
)


@pytest.mark.live
def test_exact_pong():
    chatgpt = ChatGPT()
    for _ in range(5):
        assert chatgpt.send("Reply with exactly: PONG") == "PONG"


@pytest.mark.live
def test_exact_structured_json():
    expected = {"status": "ok", "unicode": "café 世界 🤖", "lines": ["one", "two"]}
    prompt = "Return exactly this minified JSON and nothing else: " + json.dumps(
        expected, ensure_ascii=False, separators=(",", ":")
    )
    chatgpt = ChatGPT()
    for _ in range(5):
        assert json.loads(chatgpt.send(prompt)) == expected


@pytest.mark.live
def test_hard_timeout_is_clear():
    from les_cloches import LesClochesTimeout

    with pytest.raises(LesClochesTimeout):
        ChatGPT().send("Write at least 5,000 words before giving a conclusion.", timeout=5.0)


@pytest.mark.live
def test_timeout_then_recovery():
    from les_cloches import LesClochesTimeout

    chatgpt = ChatGPT()
    with pytest.raises(LesClochesTimeout):
        chatgpt.send("Write at least 5,000 words before giving a conclusion.", timeout=5.0)
    assert chatgpt.send("Reply with exactly: TIMEOUT_RECOVERED") == "TIMEOUT_RECOVERED"


@pytest.mark.live
def test_fresh_chat_isolation_with_repeated_identical_responses():
    chatgpt = ChatGPT()
    for expected in ("ISOLATION_ALPHA", "ISOLATION_BETA", "REPEATED", "REPEATED"):
        assert chatgpt.send(f"Reply with exactly: {expected}") == expected
