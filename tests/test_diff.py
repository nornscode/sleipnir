"""A change, shown as the change."""

from sleipnir import diff
from sleipnir.render import tool_result_lines

BEFORE = "def go():\n    return 1\n\n\ndef stop():\n    pass\n"
AFTER = "def go():\n    return 2\n    log()\n\n\ndef stop():\n    pass\n"


def test_a_change_reports_what_it_was():
    out = diff.summary("lib/a.py", BEFORE, AFTER)
    head, body = out.splitlines()[0], out.splitlines()[1:]

    assert head == "lib/a.py  +2 -1"
    assert any(l.startswith("@@") for l in body)
    assert "-    return 1" in body and "+    return 2" in body
    # Context comes along, so the change can be read in place.
    assert " def go():" in body


def test_nothing_changed_says_so_rather_than_showing_an_empty_diff():
    assert diff.summary("lib/a.py", BEFORE, BEFORE) == "lib/a.py: no change"


def test_a_huge_diff_is_cut_before_it_eats_the_transcript():
    big_before = "".join(f"line {i}\n" for i in range(500))
    big_after = "".join(f"changed {i}\n" for i in range(500))
    out = diff.summary("big.txt", big_before, big_after)

    assert len(out.splitlines()) <= diff.MAX_DIFF_LINES + 2
    assert "more diff lines" in out


def test_only_a_real_diff_is_read_back_as_one():
    """Ordinary tool output must not be mistaken for a change."""
    assert diff.split("wrote 14 chars to a.txt") == ("wrote 14 chars to a.txt", [])
    assert diff.split("a.py  +1 -1\nnot a diff\njust text") == ("a.py  +1 -1\nnot a diff\njust text", [])

    head, body = diff.split("a.py  +1 -1\n@@ -1,2 +1,2 @@\n-old\n+new")
    assert head == "a.py  +1 -1" and body[0].startswith("@@")


def test_the_transcript_colours_a_change_and_summarises_everything_else():
    change = "\n".join(tool_result_lines("edit_file", diff.summary("lib/a.py", BEFORE, AFTER)))
    assert "lib/a.py  +2 -1" in change
    assert "[green]+    return 2" in change
    assert "[red]-    return 1" in change

    # A failure is not a diff, whatever it contains.
    failed = "\n".join(tool_result_lines("edit_file", "old_string not found in file", is_error=True))
    assert "↳" in failed and "green" not in failed

    # And a tool that is not a change is still one line.
    listing = "\n".join(tool_result_lines("bash", "a\nb\nc\nd"))
    assert len(listing.splitlines()) == 1 and "+3 more" in listing
