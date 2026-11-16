"""Exercise the transferable script without installing packages or using hardware."""
import os
from pathlib import Path
import shutil
import subprocess


SCRIPT = Path(__file__).resolve().parents[1] / "scripts/jetson-setup.sh"


def invoke(*args, env=None):
    return subprocess.run(["bash", str(SCRIPT), *args], text=True,
                          capture_output=True, env={**os.environ, **(env or {})})


def test_help_and_unknown_action_do_not_install(tmp_path):
    settings = {"FV_LOG_DIR": str(tmp_path / "logs")}
    help_result = invoke("--help", env=settings)
    assert help_result.returncode == 0
    assert "project" in help_result.stdout and "--dry-run" in help_result.stdout
    unknown = invoke("unknown-action", env=settings)
    assert unknown.returncode == 2
    assert not (tmp_path / "logs").exists()


def test_install_rejects_non_linux_before_sudo(tmp_path):
    commands = tmp_path / "bin"
    commands.mkdir()
    marker = tmp_path / "sudo-called"
    (commands / "uname").write_text("#!/bin/sh\nprintf 'Darwin\\n'\n")
    (commands / "sudo").write_text(f"#!/bin/sh\ntouch '{marker}'\nexit 99\n")
    for path in commands.iterdir():
        path.chmod(0o755)
    result = invoke("packages", env={"PATH": f"{commands}:{os.environ['PATH']}",
                                    "FV_LOG_DIR": str(tmp_path / "logs")})
    assert result.returncode != 0
    assert "Linux" in result.stderr
    assert not marker.exists()
    assert not (tmp_path / "logs").exists()


def test_dry_run_does_not_create_directories_or_run_apt(tmp_path):
    result = invoke("--dry-run", "packages", env={"FV_LOG_DIR": str(tmp_path / "logs")})
    assert result.returncode == 0
    assert "sudo apt" in result.stdout
    assert not (tmp_path / "logs").exists()


def test_driver_dry_run_works_inside_development_venv(tmp_path):
    result = invoke("--dry-run", "driver", env={"VIRTUAL_ENV": str(tmp_path / "venv"),
                                              "FV_ORBBEC_WS": str(tmp_path / "orbbec"),
                                              "FV_LOG_DIR": str(tmp_path / "logs")})
    assert result.returncode == 0, result.stderr
    assert "colcon build" in result.stdout
    assert not (tmp_path / "orbbec").exists()
    assert not (tmp_path / "logs").exists()


def test_bundle_transfer_and_existing_checkout_preserved(tmp_path):
    source = tmp_path / "source"
    source.mkdir()
    subprocess.run(["git", "init", "-b", "main", str(source)], check=True, capture_output=True)
    (source / "README.md").write_text("offline transfer fixture\n")
    module = source / "edge/fire_vision"
    module.mkdir(parents=True)
    (module / "pyproject.toml").write_text('[project]\nname = "fixture"\n')
    subprocess.run(["git", "-C", str(source), "add", "."], check=True)
    subprocess.run(["git", "-C", str(source), "-c", "user.name=Fixture",
                    "-c", "user.email=fixture@example.invalid", "-c", "commit.gpgsign=false",
                    "commit", "-m", "fixture"], check=True, capture_output=True)
    ssd = tmp_path / "SSD with spaces"
    ssd.mkdir()
    transferred = ssd / "jetson-setup.sh"
    shutil.copyfile(SCRIPT, transferred)
    bundle = ssd / "fire-vision.bundle"
    subprocess.run(["git", "-C", str(source), "bundle", "create", str(bundle), "main"], check=True)
    target = tmp_path / "board checkout"
    settings = {**os.environ, "FV_REPO_DIR": str(target),
                "FV_PROJECT_DIR": str(target / "edge/fire_vision"),
                "FV_LOG_DIR": str(tmp_path / "logs")}
    result = subprocess.run(["bash", str(transferred), "project"], cwd=tmp_path,
                            env=settings, text=True, capture_output=True)
    assert result.returncode == 0, result.stderr + result.stdout
    assert (target / "README.md").read_text() == "offline transfer fixture\n"
    assert (target / "edge/fire_vision/pyproject.toml").is_file()
    remote = subprocess.check_output(["git", "-C", str(target), "remote", "get-url", "origin"], text=True)
    assert remote.strip() == "https://github.com/ZeroJ1nZero/RescueAI"
    (target / "README.md").write_text("board edits\n")
    again = invoke("project", env=settings)
    assert again.returncode == 0
    assert (target / "README.md").read_text() == "board edits\n"


def test_project_refuses_existing_non_repository_and_missing_bundle(tmp_path):
    target = tmp_path / "existing"
    target.mkdir()
    (target / "keep.txt").write_text("preserve me")
    settings = {"FV_REPO_DIR": str(target), "FV_PROJECT_DIR": str(target),
                "FV_LOG_DIR": str(tmp_path / "logs")}
    result = invoke("project", env=settings)
    assert result.returncode != 0
    assert "FV_REPO_DIR" in result.stdout + result.stderr
    assert (target / "keep.txt").read_text() == "preserve me"
    missing = invoke("project", str(tmp_path / "missing.bundle"),
                     env={**settings, "FV_REPO_DIR": str(tmp_path / "new")})
    assert missing.returncode != 0
    assert "missing.bundle" in missing.stdout + missing.stderr
    assert not (tmp_path / "new").exists()


def test_python_step_uses_module_inside_checkout(tmp_path):
    repo = tmp_path / "Rescue AI"
    result = invoke("--dry-run", "python", env={"FV_REPO_DIR": str(repo),
                                               "FV_LOG_DIR": str(tmp_path / "logs")})
    assert result.returncode == 0, result.stderr + result.stdout
    assert "Rescue\\ AI/edge/fire_vision/.venv-jetson/bin/python" in result.stdout
    assert "-m pip install -e" in result.stdout
    assert not repo.exists()


def test_record_requires_output_path(tmp_path):
    result = invoke("--dry-run", "record", env={"FV_LOG_DIR": str(tmp_path / "logs")})
    assert result.returncode != 0
    assert "record" in result.stderr
    assert not (tmp_path / "logs").exists()
