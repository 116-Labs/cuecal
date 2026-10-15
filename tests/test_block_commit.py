import json
import os
import shutil
import stat
import subprocess
from pathlib import Path

import pytest

HOOK_PATH = Path(__file__).resolve().parent.parent / "scripts" / "hooks" / "block_commit.sh"


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
        ["bash", str(repo / "scripts" / "hooks" / "block_commit.sh")],
        input=payload,
        text=True,
        capture_output=True,
        cwd=repo,
        env=env,
    )


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
    stub_python3 = bin_dir / "python3"
    stub_python3.write_text("#!/usr/bin/env bash\nexit 1\n")
    stub_python3.chmod(stub_python3.stat().st_mode | stat.S_IEXEC)

    # Mock working python fallback.
    real_python = shutil.which("python3")
    assert real_python is not None
    stub_python = bin_dir / "python"
    stub_python.write_text(f'#!/usr/bin/env bash\nexec "{real_python}" "$@"\n')
    stub_python.chmod(stub_python.stat().st_mode | stat.S_IEXEC)

    custom_path = f"{bin_dir}:{os.environ['PATH']}"
    payload = json.dumps({"tool_input": {"command": "git commit -m 'blocked'"}})
    proc = run_hook(repo_with_hook, payload, env_overrides={"PATH": custom_path})
    assert proc.returncode == 2
    assert "refusing `git commit` on main" in proc.stderr


def test_jq_fallback_blocks_commit_when_python_unavailable(repo_with_hook, tmp_path):
    if not shutil.which("jq"):
        pytest.skip("jq not installed on host")

    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    # Disable all python candidates.
    for name in ("python3", "python", "py"):
        stub = bin_dir / name
        stub.write_text("#!/usr/bin/env bash\nexit 1\n")
        stub.chmod(stub.stat().st_mode | stat.S_IEXEC)

    custom_path = f"{bin_dir}:{os.environ['PATH']}"
    payload = json.dumps({"tool_input": {"command": "git commit -m 'blocked'"}})
    proc = run_hook(repo_with_hook, payload, env_overrides={"PATH": custom_path})
    assert proc.returncode == 2
    assert "refusing `git commit` on main" in proc.stderr


def test_jq_fallback_allows_non_commit_when_python_unavailable(repo_with_hook, tmp_path):
    if not shutil.which("jq"):
        pytest.skip("jq not installed on host")

    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    for name in ("python3", "python", "py"):
        stub = bin_dir / name
        stub.write_text("#!/usr/bin/env bash\nexit 1\n")
        stub.chmod(stub.stat().st_mode | stat.S_IEXEC)

    custom_path = f"{bin_dir}:{os.environ['PATH']}"
    payload = json.dumps({"tool_input": {"command": "ls -la"}})
    proc = run_hook(repo_with_hook, payload, env_overrides={"PATH": custom_path})
    assert proc.returncode == 0


def test_jq_fallback_refuses_missing_command(repo_with_hook, tmp_path):
    if not shutil.which("jq"):
        pytest.skip("jq not installed on host")

    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    for name in ("python3", "python", "py"):
        stub = bin_dir / name
        stub.write_text("#!/usr/bin/env bash\nexit 1\n")
        stub.chmod(stub.stat().st_mode | stat.S_IEXEC)

    custom_path = f"{bin_dir}:{os.environ['PATH']}"
    payload = json.dumps({"tool_input": {}})
    proc = run_hook(repo_with_hook, payload, env_overrides={"PATH": custom_path})
    assert proc.returncode == 2
    assert "unable to parse hook input" in proc.stderr


def test_sed_fallback_blocks_commit_when_python_and_jq_unavailable(repo_with_hook, tmp_path):
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    for name in ("python3", "python", "py", "jq"):
        stub = bin_dir / name
        stub.write_text("#!/usr/bin/env bash\nexit 1\n")
        stub.chmod(stub.stat().st_mode | stat.S_IEXEC)

    clean_bin = tmp_path / "clean_bin"
    clean_bin.mkdir()
    for tool in ("bash", "cat", "git", "sed", "tr", "dirname", "cut"):
        real = shutil.which(tool)
        if real:
            (clean_bin / tool).symlink_to(real)

    payload = json.dumps({"tool_input": {"command": "git commit -m 'blocked'"}})
    proc = run_hook(repo_with_hook, payload, env_overrides={"PATH": str(clean_bin)})
    assert proc.returncode == 2
    assert "refusing `git commit` on main" in proc.stderr


def test_sed_fallback_allows_non_commit_when_python_and_jq_unavailable(repo_with_hook, tmp_path):
    clean_bin = tmp_path / "clean_bin"
    clean_bin.mkdir()
    for tool in ("bash", "cat", "git", "sed", "tr", "dirname", "cut"):
        real = shutil.which(tool)
        if real:
            (clean_bin / tool).symlink_to(real)

    payload = json.dumps({"tool_input": {"command": "echo 'hello world'"}})
    proc = run_hook(repo_with_hook, payload, env_overrides={"PATH": str(clean_bin)})
    assert proc.returncode == 0


def test_sed_fallback_refuses_unicode_escapes(repo_with_hook, tmp_path):
    clean_bin = tmp_path / "clean_bin"
    clean_bin.mkdir()
    for tool in ("bash", "cat", "git", "sed", "tr", "dirname", "cut"):
        real = shutil.which(tool)
        if real:
            (clean_bin / tool).symlink_to(real)

    payload = r'{"tool_input": {"command": "git\u0020commit -m blocked"}}'
    proc = run_hook(repo_with_hook, payload, env_overrides={"PATH": str(clean_bin)})
    assert proc.returncode == 2
    assert "without python or jq" in proc.stderr


def test_sed_fallback_refuses_missing_command(repo_with_hook, tmp_path):
    clean_bin = tmp_path / "clean_bin"
    clean_bin.mkdir()
    for tool in ("bash", "cat", "git", "sed", "tr", "dirname", "cut"):
        real = shutil.which(tool)
        if real:
            (clean_bin / tool).symlink_to(real)

    payload = '{"tool_input": {}}'
    proc = run_hook(repo_with_hook, payload, env_overrides={"PATH": str(clean_bin)})
    assert proc.returncode == 2
    assert "without python or jq" in proc.stderr
