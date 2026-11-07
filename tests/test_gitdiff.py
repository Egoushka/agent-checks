from agent_checks.gitdiff import parse_diff


def test_path_with_space_loses_the_tab_git_appends():
    diff = (
        "diff --git a/my dir/a.py b/my dir/a.py\n"
        "--- a/my dir/a.py\t\n"
        "+++ b/my dir/a.py\t\n"
        "@@ -0,0 +1 @@\n"
        "+x = 1\n"
    )
    [change] = parse_diff(diff)
    assert change.path == "my dir/a.py"


def test_lines_are_split_on_newline_only():
    # str.splitlines() also breaks on \x0b \x0c \x1c-\x1e \x85     and a lone \r
    diff = "diff --git a/a.txt b/a.txt\n--- a/a.txt\n+++ b/a.txt\n@@ -0,0 +1,2 @@\n+one\x0btwo\x85three four\rfive\n+six\n"
    [change] = parse_diff(diff)
    assert change.added == {1: "one\x0btwo\x85three four\rfive", 2: "six"}


def test_crlf_line_keeps_its_carriage_return():
    diff = "diff --git a/a.txt b/a.txt\n--- a/a.txt\n+++ b/a.txt\n@@ -1 +1 @@\n-old\r\n+new\r\n"
    [change] = parse_diff(diff)
    assert change.added == {1: "new\r"}
    assert change.removed == ["old\r"]


def test_quoted_binary_path_is_matched_and_unquoted():
    diff = (
        'diff --git "a/tab\\tname.bin" "b/tab\\tname.bin"\n'
        "index 1111111..2222222 100644\n"
        'Binary files "a/tab\\tname.bin" and "b/tab\\tname.bin" differ\n'
        'diff --git a/gone.bin b/gone.bin\n'
        "deleted file mode 100644\n"
        'Binary files "a/q\\"uote.bin" and /dev/null differ\n'
    )
    changed, gone = parse_diff(diff)
    assert (changed.path, changed.binary) == ("tab\tname.bin", True)
    assert (gone.path, gone.binary, gone.deleted) == ('q"uote.bin', True, True)
