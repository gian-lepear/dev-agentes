import os
import subprocess
import sys
from collections.abc import Callable
from pathlib import Path

import pytest

SCRIPTS = Path(__file__).resolve().parent.parent / "scripts"
sys.path.insert(0, str(SCRIPTS))


def git(repo: Path, *args: str) -> str:
    resultado = subprocess.run(
        ["git", "-C", str(repo), *args], check=True, capture_output=True, text=True
    )
    return resultado.stdout.strip()


@pytest.fixture(autouse=True)
def _git_limpo(monkeypatch: pytest.MonkeyPatch) -> None:
    for variavel in [v for v in os.environ if v.startswith("GIT_")]:
        monkeypatch.delenv(variavel)
    monkeypatch.delenv("PRE_COMMIT_TO_REF", raising=False)
    monkeypatch.setenv("GIT_CONFIG_NOSYSTEM", "1")
    monkeypatch.setenv("GIT_CONFIG_GLOBAL", os.devnull)


@pytest.fixture
def repo(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    raiz = tmp_path / "repo"
    raiz.mkdir()
    git(raiz, "init", "-q", "-b", "main")
    git(raiz, "config", "user.email", "ci@exemplo")
    git(raiz, "config", "user.name", "ci")
    git(raiz, "config", "commit.gpgsign", "false")
    (raiz / ".gitignore").write_text(".local/\n__pycache__/\n", encoding="utf-8")
    commita(raiz, "a.py", "a = 1\n")
    monkeypatch.chdir(raiz)
    return raiz


def commita(repo: Path, arquivo: str, conteudo: str) -> None:
    (repo / arquivo).parent.mkdir(parents=True, exist_ok=True)
    (repo / arquivo).write_text(conteudo, encoding="utf-8")
    git(repo, "add", "-A")
    git(repo, "commit", "-q", "-m", arquivo)


@pytest.fixture
def commit() -> Callable[[Path, str, str], None]:
    return commita
