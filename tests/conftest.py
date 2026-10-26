import json
import subprocess
from pathlib import Path

import pytest

from agent_checks import cli


class Repo:
    def __init__(self, root: Path):
        self.root = root
        self.git("init", "-q", "-b", "main")
        self.git("config", "user.email", "t@example.com")
        self.git("config", "user.name", "t")
        self.git("config", "commit.gpgsign", "false")
        self.write(".agent-checks.toml", "")
        self.commit("init")

    def git(self, *args: str) -> str:
        return subprocess.run(["git", *args], cwd=self.root, check=True, capture_output=True, text=True).stdout

    def write(self, path: str, text: str) -> None:
        p = self.root / path
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(text)

    def commit(self, msg: str = "c") -> None:
        self.git("add", "-A")
        self.git("commit", "-q", "--allow-empty", "-m", msg)

    def check(self, *args: str) -> tuple[int, dict]:
        import contextlib
        import io

        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            code = cli.main(["check", "-C", str(self.root), "--format", "json", *args])
        return code, json.loads(buf.getvalue())

    def rules(self, *args: str, key: str = "findings") -> list[str]:
        return sorted({f["rule"].split(":")[0] for f in self.check(*args)[1][key]})


@pytest.fixture
def repo(tmp_path, monkeypatch):
    monkeypatch.delenv("AGENT_CHECKS_ALLOW", raising=False)
    monkeypatch.delenv("AGENT_CHECKS_SCOPE", raising=False)
    return Repo(tmp_path)
