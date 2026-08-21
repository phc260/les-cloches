import os

import pytest

from les_cloches import Claude

pytestmark = pytest.mark.skipif(
    os.environ.get("LES_CLOCHES_LIVE") != "1",
    reason="set LES_CLOCHES_LIVE=1 to control the real Claude Desktop GUI",
)


@pytest.mark.live
def test_exact_pong():
    claude = Claude()
    for _ in range(5):
        assert claude.send("Reply with exactly AVFD_PONG") == "AVFD_PONG"


@pytest.mark.live
def test_exact_json():
    import json

    prompt = 'Return exactly this JSON and nothing else:\n{"status":"AVFD_PONG","number":42}'
    claude = Claude()
    for _ in range(5):
        assert json.loads(claude.send(prompt)) == {"status": "AVFD_PONG", "number": 42}


@pytest.mark.live
def test_multiline_unicode_and_punctuation():
    payload = """Markdown: **bold** and `code`
Quotes: \"double\" and 'single'
Unicode: café, 日本語, snowman ☃
JSON: {\"items\":[1,2,3]}
Grouping: (round) [square] {curly}
Path: /var/tmp/AVFD bridge/input.json
Final line."""
    prompt = (
        "Return exactly the text between BEGIN and END, preserving every character "
        "and newline, with no fences.\nBEGIN\n" + payload + "\nEND"
    )
    assert Claude().send(prompt) == payload


@pytest.mark.live
def test_hard_timeout_is_clear():
    from les_cloches import LesClochesTimeout

    with pytest.raises(LesClochesTimeout):
        Claude().send("Write a detailed 5,000 word essay.", timeout=0.2)


@pytest.mark.live
def test_timeout_then_recovery():
    from les_cloches import LesClochesTimeout

    claude = Claude()
    with pytest.raises(LesClochesTimeout):
        claude.send("Write a detailed 5,000 word essay.", timeout=0.2)
    assert claude.send("Reply with exactly TIMEOUT_RECOVERED") == "TIMEOUT_RECOVERED"


@pytest.mark.live
def test_fresh_chat_isolation_with_repeated_identical_responses():
    claude = Claude()
    for expected in ("ISOLATION_ALPHA", "ISOLATION_BETA", "REPEATED", "REPEATED"):
        assert claude.send(f"Reply with exactly: {expected}") == expected
