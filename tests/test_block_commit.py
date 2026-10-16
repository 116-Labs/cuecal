import json
import os
import shutil
import stat
import subprocess
import sys
from pathlib import Path

import pytest

HOOK_PATH = Path(__file__).resolve().parent.parent / "scripts" / "hooks" / "block_commit.sh"
IS_WINDOWS = os.name == "nt"
# Tools the hook's sed fallback needs; a PATH holding only these hides python and jq.
SED_PATH_TOOLS = ("bash", "cat", "git", "sed", "tr", "dirname", "cut")


def _git_bash_root() -> Path | None:
    git = shutil.which("git")
    if git is None:
        return None
    # Git for Windows puts git.exe in <root>/cmd or <root>/mingw64/bin.
    for root in Path(git).resolve().parents:
        if (root / "usr" / "bin" / "bash.exe").is_file():
            return root
    return None


def _resolve_bash() -> str | None:
    # On Windows a bare `bash` is System32's WSL launcher, not Git Bash.
    if IS_WINDOWS:
        root = _git_bash_root()
        return str(root / "usr" / "bin" / "bash.exe") if root else None
    return shutil.which("bash")


BASH = _resolve_bash()
pytestmark = pytest.mark.skipif(BASH is None, reason="no Git Bash / bash found")


@pytest.fixture
def repo_with_hook(tmp_path):
    repo = tmp_path / "repo"
    repo.mkdir()
    hooks_dir = repo / "scripts" / "hooks"
    hooks_dir.mkdir(parents=True)
    hook_dest = hooks_dir / "block_commit.sh"
    shutil.copy2(HOOK_PATH, hook_dest)
    hook_dest.chmod(hook_dest.stat().st_mode | stat.S_IEXEC)

    subprocess.run(["git", "init", "-b", "main"], cwd=repo, check=True, capture_output=True)
    subprocess.run(["git", "config", "user.name", "Test User"], cwd=repo, check=True)
    subprocess.run(["git", "config", "user.email", "test@example.com"], cwd=repo, check=True)
    (repo / "tracked.txt").write_text("initial")
    subprocess.run(["git", "add", "."], cwd=repo, check=True)
    subprocess.run(["git", "commit", "-m", "init"], cwd=repo, check=True, capture_output=True)
    return repo


def run_hook(
    repo: Path, payload: str, env_overrides: dict[str, str] | None = None
) -> subprocess.CompletedProcess:
    env = os.environ.copy()
    if env_overrides:
        env.update(env_overrides)
    return subprocess.run(
        [BASH, (repo / "scripts" / "hooks" / "block_commit.sh").as_posix()],
        input=payload,
        text=True,
        capture_output=True,
        cwd=repo,
        env=env,
    )


def write_stub(path: Path, body: str = "exit 1") -> None:
    path.write_text(f"#!/usr/bin/env bash\n{body}\n", newline="\n")
    path.chmod(path.stat().st_mode | stat.S_IEXEC)


def path_with(bin_dir: Path) -> str:
    return f"{bin_dir}{os.pathsep}{os.environ['PATH']}"


def sed_only_path(tmp_path: Path) -> str:
    """A PATH with the sed fallback's tools but no python or jq."""
    if IS_WINDOWS:
        # Git Bash's tools need msys-2.0.dll beside them, so use its dirs as-is.
        root = _git_bash_root()
        path = os.pathsep.join([str(root / "usr" / "bin"), str(Path(shutil.which("git")).parent)])
        for name in ("python3", "python", "py", "jq"):
            if shutil.which(name, path=path):
                pytest.skip(f"{name} ships beside Git Bash, so it cannot be hidden")
        return path
    clean_bin = tmp_path / "clean_bin"
    clean_bin.mkdir()
    for tool in SED_PATH_TOOLS:
        real = shutil.which(tool)
        if real:
            (clean_bin / tool).symlink_to(real)
    return str(clean_bin)


def test_skip_hooks_env_allows_commit_on_main(repo_with_hook):
    payload = json.dumps({"tool_input": {"command": "git commit -m 'on main'"}})
    proc = run_hook(repo_with_hook, payload, env_overrides={"CUECAL_SKIP_HOOKS": "1"})
    assert proc.returncode == 0


def test_python_blocks_git_commit_on_main(repo_with_hook):
    payload = json.dumps({"tool_input": {"command": "git commit -m 'blocked'"}})
    proc = run_hook(repo_with_hook, payload)
    assert proc.returncode == 2
    assert "refusing `git commit` on main" in proc.stderr


def test_python_allows_git_commit_on_feature_branch(repo_with_hook):
    subprocess.run(["git", "switch", "-c", "feature/test"], cwd=repo_with_hook, check=True)
    payload = json.dumps({"tool_input": {"command": "git commit -m 'allowed'"}})
    proc = run_hook(repo_with_hook, payload)
    assert proc.returncode == 0


def test_python_allows_non_commit_command(repo_with_hook):
    payload = json.dumps({"tool_input": {"command": "git status"}})
    proc = run_hook(repo_with_hook, payload)
    assert proc.returncode == 0


def test_python_refuses_malformed_json_input(repo_with_hook):
    proc = run_hook(repo_with_hook, "not json")
    assert proc.returncode == 2
    assert "unable to parse hook input" in proc.stderr


def test_fallback_to_second_python_candidate_when_first_fails(repo_with_hook, tmp_path):
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    # Mock broken python3 stub (simulates Windows store stub).
    write_stub(bin_dir / "python3")
    # Mock working python fallback.
    write_stub(bin_dir / "python", f'exec "{Path(sys.executable).as_posix()}" "$@"')

    payload = json.dumps({"tool_input": {"command": "git commit -m 'blocked'"}})
    proc = run_hook(repo_with_hook, payload, env_overrides={"PATH": path_with(bin_dir)})
    assert proc.returncode == 2
    assert "refusing `git commit` on main" in proc.stderr


def _no_python_path(tmp_path: Path) -> str:
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    for name in ("python3", "python", "py"):
        write_stub(bin_dir / name)
    return path_with(bin_dir)


def test_jq_fallback_blocks_commit_when_python_unavailable(repo_with_hook, tmp_path):
    if not shutil.which("jq"):
        pytest.skip("jq not installed on host")

    payload = json.dumps({"tool_input": {"command": "git commit -m 'blocked'"}})
    proc = run_hook(repo_with_hook, payload, env_overrides={"PATH": _no_python_path(tmp_path)})
    assert proc.returncode == 2
    assert "refusing `git commit` on main" in proc.stderr


def test_jq_fallback_allows_non_commit_when_python_unavailable(repo_with_hook, tmp_path):
    if not shutil.which("jq"):
        pytest.skip("jq not installed on host")

    payload = json.dumps({"tool_input": {"command": "ls -la"}})
    proc = run_hook(repo_with_hook, payload, env_overrides={"PATH": _no_python_path(tmp_path)})
    assert proc.returncode == 0


def test_jq_fallback_refuses_missing_command(repo_with_hook, tmp_path):
    if not shutil.which("jq"):
        pytest.skip("jq not installed on host")

    payload = json.dumps({"tool_input": {}})
    proc = run_hook(repo_with_hook, payload, env_overrides={"PATH": _no_python_path(tmp_path)})
    assert proc.returncode == 2
    assert "unable to parse hook input" in proc.stderr


def test_sed_fallback_blocks_commit_when_python_and_jq_unavailable(repo_with_hook, tmp_path):
    payload = json.dumps({"tool_input": {"command": "git commit -m 'blocked'"}})
    proc = run_hook(repo_with_hook, payload, env_overrides={"PATH": sed_only_path(tmp_path)})
    assert proc.returncode == 2
    assert "refusing `git commit` on main" in proc.stderr


def test_sed_fallback_allows_non_commit_when_python_and_jq_unavailable(repo_with_hook, tmp_path):
    payload = json.dumps({"tool_input": {"command": "echo 'hello world'"}})
    proc = run_hook(repo_with_hook, payload, env_overrides={"PATH": sed_only_path(tmp_path)})
    assert proc.returncode == 0


def test_sed_fallback_refuses_unicode_escapes(repo_with_hook, tmp_path):
    payload = r'{"tool_input": {"command": "git\u0020commit -m blocked"}}'
    proc = run_hook(repo_with_hook, payload, env_overrides={"PATH": sed_only_path(tmp_path)})
    assert proc.returncode == 2
    assert "without python or jq" in proc.stderr


def test_sed_fallback_refuses_missing_command(repo_with_hook, tmp_path):
    payload = '{"tool_input": {}}'
    proc = run_hook(repo_with_hook, payload, env_overrides={"PATH": sed_only_path(tmp_path)})
    assert proc.returncode == 2
    assert "without python or jq" in proc.stderr
