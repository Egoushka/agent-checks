"""Each case: a file and its content; `bad` must raise the rule, `good` (the fix) must not."""

import pytest

CASES = [
    # rule, path, bad, good
    (
        "skip-test",
        "tests/FooTests.cs",
        '[Fact(Skip = "flaky")]\npublic void A() { Assert.Equal(1, F()); }\n',
        "[Fact]\npublic void A() { Assert.Equal(1, F()); }\n",
    ),
    ("skip-test", "src/test/FooTest.kt", "@Disabled\n@Test fun a() { assertEquals(1, f()) }\n", "@Test fun a() { assertEquals(1, f()) }\n"),
    ("skip-test", "tests/test_a.py", "@pytest.mark.skip\ndef test_a():\n    assert f() == 1\n", "def test_a():\n    assert f() == 1\n"),
    ("skip-test", "src/a.test.ts", "it.skip('a', () => { expect(f()).toBe(1) })\n", "it('a', () => { expect(f()).toBe(1) })\n"),
    ("focused-test", "src/a.test.ts", "it.only('a', () => { expect(f()).toBe(1) })\n", "it('a', () => { expect(f()).toBe(1) })\n"),
    ("tautology", "tests/ATests.cs", "[Fact] public void A() { Assert.True(true); }\n", "[Fact] public void A() { Assert.True(F()); }\n"),
    ("tautology", "tests/test_a.py", "def test_a():\n    assert True\n", "def test_a():\n    assert f()\n"),
    ("tautology", "src/a.spec.js", "it('a', () => { expect(x).toBe(x) })\n", "it('a', () => { expect(x).toBe(2) })\n"),
    (
        "test-without-assert",
        "tests/ATests.cs",
        "class T {\n  [Fact]\n  public void A() { var x = F(); }\n}\n",
        "class T {\n  [Fact]\n  public void A() { Assert.Equal(1, F()); }\n}\n",
    ),
    ("test-without-assert", "tests/test_a.py", "def test_a():\n    f()\n", "def test_a():\n    assert f() == 1\n"),
    ("test-without-assert", "src/a.test.ts", "test('a', () => { f() })\n", "test('a', () => { expect(f()).toBe(1) })\n"),
    (
        "test-without-assert",
        "app/src/test/ATest.kt",
        "class T {\n  @Test\n  fun a() { val x = f() }\n}\n",
        "class T {\n  @Test\n  fun a() { assertEquals(1, f()) }\n}\n",
    ),
    ("sleep-in-test", "tests/ATests.cs", "[Fact] public void A() { Thread.Sleep(500); Assert.True(F()); }\n", "[Fact] public void A() { Assert.True(F()); }\n"),
    ("sleep-in-test", "tests/test_a.py", "def test_a():\n    time.sleep(1)\n    assert f()\n", "def test_a():\n    assert f()\n"),
    (
        "empty-catch",
        "src/A.cs",
        "class A { void M() { try { F(); } catch (Exception) { } } }\n",
        "class A { void M() { try { F(); } catch (IOException e) { log.Warn(e); throw; } } }\n",
    ),
    ("empty-catch", "src/a.py", "try:\n    f()\nexcept ValueError:\n    pass\n", "try:\n    f()\nexcept ValueError:\n    log.warning('x')\n"),
    ("empty-catch", "src/a.ts", "try { f() } catch (e) { }\n", "try { f() } catch (e) { log(e) }\n"),
    ("empty-catch", "src/A.kt", "fun a() {\n  try { f() } catch (e: Exception) { }\n}\n", "fun a() {\n  try { f() } catch (e: IOException) { log(e) }\n}\n"),
    ("bare-except", "src/a.py", "try:\n    f()\nexcept:\n    raise\n", "try:\n    f()\nexcept OSError:\n    raise\n"),
    ("rethrow-loses-stack", "src/A.cs", "catch (Exception ex) { Log(ex); throw ex; }\n", "catch (Exception ex) { Log(ex); throw; }\n"),
    ("async-void", "src/A.cs", "public async void Run() { await F(); }\n", "public async Task Run() { await F(); }\n"),
    ("suppress-warning", "src/A.cs", "#pragma warning disable CS8618\n", 'public string Name { get; init; } = "";\n'),
    ("suppress-warning", "src/a.py", "import os  # noqa\n", "import os\n"),
    ("suppress-warning", "src/a.ts", "// @ts-ignore\nconst x: number = y\n", "const x: number = Number(y)\n"),
    (
        "suppress-warning",
        "src/A.kt",
        '@Suppress("TooGenericExceptionCaught")\nfun a() = 1\n',
        '@Suppress("TooGenericExceptionCaught") // a provider can fail in any way\nfun a() = 1\n',
    ),
    (
        "weakened-gate",
        "Directory.Build.props",
        "<Project><PropertyGroup><TreatWarningsAsErrors>false</TreatWarningsAsErrors></PropertyGroup></Project>\n",
        "<Project><PropertyGroup><TreatWarningsAsErrors>true</TreatWarningsAsErrors></PropertyGroup></Project>\n",
    ),
    (
        "weakened-gate",
        ".github/workflows/ci.yml",
        "jobs:\n  t:\n    steps:\n      - run: dotnet test\n        continue-on-error: true\n",
        "jobs:\n  t:\n    steps:\n      - run: dotnet test\n",
    ),
    ("stub", "src/A.cs", "public int F() => throw new NotImplementedException();\n", "public int F() => 1;\n"),
    ("stub", "src/a.py", "def f():\n    raise NotImplementedError\n", "def f():\n    return 1\n"),
    ("todo-comment", "src/A.cs", "// TODO: handle retries\nvar x = 1;\n", "// TODO(#42): handle retries\nvar x = 1;\n"),
    ("commented-out-code", "src/A.cs", "// var old = Compute(x);\nvar y = 1;\n", "// The old path computed this eagerly.\nvar y = 1;\n"),
    ("commented-out-code", "src/a.py", "# import json\nx = 1\n", "# json is imported lazily below\nx = 1\n"),
    ("debug-leftover", "src/a.ts", "debugger;\nf()\n", "f()\n"),
    ("debug-leftover", "src/a.py", "breakpoint()\nf()\n", "f()\n"),
    ("merge-conflict", "src/a.txt", "<<<<<<< HEAD\na\n=======\nb\n>>>>>>> x\n", "a\n"),
    ("merge-conflict", "docs/a.md", "text\n||||||| cd8baa8\nmore\n", "text\nmore\n"),
    ("private-key", "deploy/key.txt", "-----BEGIN OPENSSH PRIVATE KEY-----\nabc\n", "see vault://deploy/key\n"),
    ("trailing-whitespace", "src/a.py", "x = 1   \n", "x = 1\n"),
    ("final-newline", "src/a.py", "x = 1", "x = 1\n"),
    ("plaintext-env", ".env", "TOKEN=abc\n", None),
    ("typo", "src/a.py", "# teh value\nx = 1\n", "# the value\nx = 1\n"),
    ("ruff", "src/a.py", "def f():\n    return undefined_name\n", "def f(undefined_name):\n    return undefined_name\n"),
    (
        "allow-without-reason",
        "src/A.cs",
        "#pragma warning disable CS1 // agent-checks: allow suppress-warning\n",
        "#pragma warning disable CS1 // agent-checks: allow suppress-warning -- generated interop signature\n",
    ),
]


WARN = {"typo", "final-newline", "trailing-whitespace"}


@pytest.mark.parametrize("rule,path,bad,good", CASES, ids=[f"{c[0]}:{c[1]}" for c in CASES])
def test_rule(repo, rule, path, bad, good):
    key = "warnings" if rule in WARN else "findings"
    repo.write(path, bad)
    repo.git("add", "-A")
    assert rule in repo.rules("--staged", key=key), f"{rule} should fire on:\n{bad}"
    if good is None:
        return
    repo.write(path, good)
    repo.git("add", "-A")
    assert rule not in repo.rules("--staged", key=key), f"{rule} should not fire on:\n{good}"


def test_only_added_lines_count(repo):
    repo.write("tests/ATests.cs", '[Fact(Skip = "old")]\npublic void A() { Assert.Equal(1, F()); }\n')
    repo.commit()
    repo.write("tests/ATests.cs", '[Fact(Skip = "old")]\npublic void A() { Assert.Equal(1, F()); }\n[Fact]\npublic void B() { Assert.Equal(2, G()); }\n')
    repo.git("add", "-A")
    code, out = repo.check("--staged")
    assert code == 0, out


def test_allow_marker_with_reason(repo):
    repo.write("src/A.cs", "// agent-checks: allow suppress-warning -- source generator needs instance methods\n#pragma warning disable CA1822\n")
    repo.git("add", "-A")
    code, out = repo.check("--staged")
    assert code == 0 and [f["rule"] for f in out["allowed"]] == ["suppress-warning"]


def test_marker_on_line_above(repo):
    repo.write("src/a.py", "# agent-checks: allow stub -- abstract hook that plugins override\ndef f():\n    raise NotImplementedError\n")
    repo.git("add", "-A")
    assert repo.check("--staged")[0] == 0


def test_unallowable_rule_ignores_marker(repo):
    repo.write("src/a.test.ts", "it.only('a', () => { expect(f()).toBe(1) }) // agent-checks: allow focused-test -- debugging one case\n")
    repo.git("add", "-A")
    assert "focused-test" in repo.rules("--staged")


def test_abstract_stub_is_fine(repo):
    repo.write("src/a.py", "class A(ABC):\n    @abstractmethod\n    def f(self):\n        raise NotImplementedError\n")
    repo.git("add", "-A")
    assert "stub" not in repo.rules("--staged")


def test_partial_staging_uses_index_content(repo):
    repo.write("src/A.cs", "class A {\n}\n")
    repo.commit()
    repo.write("src/A.cs", "class A {\n  void M() { try { F(); } catch (Exception) { } }\n}\n")
    repo.git("add", "-A")
    # Unstaged edit above the bad line shifts worktree line numbers; the check must read the index.
    repo.write("src/A.cs", "// header\n// more\nclass A {\n  void M() { try { F(); } catch (Exception) { } }\n}\n")
    _, out = repo.check("--staged")
    hits = [f for f in out["findings"] if f["rule"] == "empty-catch"]
    assert [f["line"] for f in hits] == [2]


def test_deleted_tests_and_env_allow(repo, monkeypatch):
    repo.write("tests/test_a.py", "def test_a():\n    assert f() == 1\n\ndef test_b():\n    assert g() == 2\n")
    repo.commit()
    repo.write("tests/test_a.py", "def test_a():\n    assert f() == 1\n")
    repo.git("add", "-A")
    assert {"deleted-tests", "deleted-assertions"} <= set(repo.rules("--staged"))
    monkeypatch.setenv("AGENT_CHECKS_ALLOW", "deleted-tests: g() was removed in this change; deleted-assertions: same reason as above")
    assert repo.check("--staged")[0] == 0


def test_out_of_scope(repo, monkeypatch):
    repo.write("src/a.py", "x = 1\n")
    repo.write("docs/b.md", "hello\n")
    repo.git("add", "-A")
    monkeypatch.setenv("AGENT_CHECKS_SCOPE", "src/**")
    _, out = repo.check("--staged")
    assert [(f["rule"], f["path"]) for f in out["findings"]] == [("out-of-scope", "docs/b.md")]


def test_base_mode_sees_committed_and_uncommitted(repo):
    repo.git("checkout", "-q", "-b", "feature")
    repo.write("src/A.cs", "public async void Run() { await F(); }\n")
    repo.commit()
    repo.write("src/B.cs", "public int F() => throw new NotImplementedException();\n")
    assert repo.rules("--base", "main") == ["async-void", "stub"]


def test_commit_mode(repo):
    repo.write("src/a.py", "breakpoint()\n")
    repo.commit()
    assert "debug-leftover" in repo.rules("--commit", "HEAD")


def test_config_disable_and_exclude(repo):
    repo.write(".agent-checks.toml", 'disable = ["todo-comment"]\nexclude = ["legacy/**"]\n')
    repo.commit()
    repo.write("src/a.py", "# TODO later\nx = 1\n")
    repo.write("legacy/b.py", "breakpoint()\n")
    repo.git("add", "-A")
    assert repo.check("--staged")[0] == 0


def test_unknown_rule_in_config_is_an_error(repo):
    repo.write(".agent-checks.toml", 'disable = ["no-such-rule"]\n')
    repo.git("add", "-A")
    from agent_checks import cli

    assert cli.main(["check", "-C", str(repo.root), "--staged"]) == 3


def test_warnings_do_not_fail(repo):
    repo.write("docs/a.md", "teh end")
    repo.git("add", "-A")
    code, out = repo.check("--staged")
    assert code == 0 and {f["rule"] for f in out["warnings"]} == {"typo", "final-newline"}


def test_severity_override(repo):
    repo.write(".agent-checks.toml", 'error = ["final-newline"]\n')
    repo.commit()
    repo.write("src/a.py", "x = 1")
    repo.git("add", "-A")
    assert repo.rules("--staged") == ["final-newline"]


def test_feature_removal_is_not_test_deletion(repo):
    repo.write("src/feature.py", "def f():\n    return 1\n")
    repo.write("tests/test_feature.py", "def test_f():\n    assert f() == 1\n")
    repo.commit()
    repo.git("rm", "-q", "src/feature.py", "tests/test_feature.py")
    assert repo.check("--staged")[0] == 0


def test_moved_test_is_not_deletion(repo):
    repo.write("tests/test_a.py", "def test_a():\n    assert f() == 1\n")
    repo.commit()
    repo.git("rm", "-q", "tests/test_a.py")
    repo.write("tests/test_b.py", "def test_a():\n    assert f() == 1\n")
    repo.git("add", "-A")
    assert repo.check("--staged")[0] == 0


def test_same_file_assert_helper(repo):
    repo.write("src/test/ATest.kt", "class T {\n  private fun shows(x: Int) { onNode(x).assertExists() }\n  @Test\n  fun a() = shows(1)\n}\n")
    repo.git("add", "-A")
    assert "test-without-assert" not in repo.rules("--staged")
