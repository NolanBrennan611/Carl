"""CLI behavior, including exit codes (acceptance criteria for Phase 1)."""

import subprocess
import sys

import pytest

from carl import cli
from carl.lockfile import InstanceLock
from tests.conftest import TOKEN, make_env


def run_cli(*args, env, cwd):
    return subprocess.run(
        [sys.executable, "-m", "carl", *args],
        env=env,
        cwd=cwd,
        capture_output=True,
        text=True,
        timeout=60,
    )


@pytest.fixture
def clean_env(tmp_path, monkeypatch):
    for key in list(__import__("os").environ):
        if key.startswith(("CARL_", "DISCORD_")):
            monkeypatch.delenv(key)
    monkeypatch.chdir(tmp_path)  # so a developer's real .env is never loaded
    return tmp_path


def test_check_config_without_token_exits_2_and_names_variable(clean_env, monkeypatch, capsys):
    for k, v in make_env(clean_env / "data").items():
        if k != "DISCORD_TOKEN":
            monkeypatch.setenv(k, v)
    assert cli.main(["check-config"]) == 2
    assert "DISCORD_TOKEN" in capsys.readouterr().err


def test_check_config_ok_never_prints_the_token(clean_env, monkeypatch, capsys):
    for k, v in make_env(clean_env / "data").items():
        monkeypatch.setenv(k, v)
    assert cli.main(["check-config"]) == 0
    out = capsys.readouterr().out
    assert "Configuration OK" in out
    assert TOKEN not in out
    assert TOKEN[-4:] in out


def test_run_with_bad_config_exits_2(clean_env):
    assert cli.main(["run"]) == 2


def test_no_subcommand_prints_help_and_fails(clean_env, capsys):
    assert cli.main([]) == 2
    assert "usage" in capsys.readouterr().out.lower()


def test_migrate_and_status(clean_env, monkeypatch, capsys):
    monkeypatch.setenv("CARL_DATA_DIR", str(clean_env / "data"))
    assert cli.main(["migrate", "--status"]) == 0
    assert "pending: [1]" in capsys.readouterr().out
    assert cli.main(["migrate"]) == 0
    assert "applied migrations: [1]" in capsys.readouterr().out
    assert cli.main(["migrate"]) == 0
    assert "up to date" in capsys.readouterr().out
    assert cli.main(["migrate", "--status"]) == 0
    assert "applied: [1]" in capsys.readouterr().out


def test_backup_command(clean_env, monkeypatch, capsys):
    monkeypatch.setenv("CARL_DATA_DIR", str(clean_env / "data"))
    assert cli.main(["backup"]) == 2  # no database yet
    cli.main(["migrate"])
    capsys.readouterr()
    assert cli.main(["backup"]) == 0
    assert list((clean_env / "data" / "backups").glob("manual-*.db"))


def test_second_instance_on_same_data_dir_exits_3(clean_env, monkeypatch):
    data = clean_env / "data"
    for k, v in make_env(data).items():
        monkeypatch.setenv(k, v)
    with InstanceLock(data / "carl.lock"):
        assert cli.main(["run"]) == 3


def test_module_entry_point_runs_as_subprocess(clean_env):
    import os

    env = {k: v for k, v in os.environ.items() if not k.startswith(("CARL_", "DISCORD_"))}
    result = run_cli("check-config", env=env, cwd=clean_env)
    assert result.returncode == 2
    assert "DISCORD_TOKEN" in result.stderr
