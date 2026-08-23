from __future__ import annotations

import json
import os
from pathlib import Path
import subprocess

ROOT = Path(__file__).resolve().parents[2]


def fake_docker(tmp_path: Path, *, image_exists: bool) -> tuple[Path, Path]:
    capture = tmp_path / "docker-calls.jsonl"
    script = tmp_path / "docker"
    script.write_text(
        "#!/usr/bin/env python3\n"
        "import json, os, sys\n"
        "path = os.environ['SAFEPLANE_TEST_DOCKER_CALLS']\n"
        "with open(path, 'a', encoding='utf-8') as handle:\n"
        "    handle.write(json.dumps(sys.argv[1:]) + '\\n')\n"
        f"image_exists = {image_exists!r}\n"
        "if sys.argv[1:3] == ['image', 'inspect']:\n"
        "    raise SystemExit(0 if image_exists else 1)\n"
        "if 'build' in sys.argv:\n"
        "    print('compose build progress', file=sys.stderr)\n"
        "if 'run' in sys.argv and os.environ.get('COMPOSE_PROGRESS') != 'quiet':\n"
        "    print('compose run progress', file=sys.stderr)\n",
        encoding="utf-8",
    )
    script.chmod(0o755)
    return script, capture


def run_launcher(tmp_path: Path, *args: str, image_exists: bool = True) -> tuple[subprocess.CompletedProcess[str], list[list[str]]]:
    _, capture = fake_docker(tmp_path, image_exists=image_exists)
    env = os.environ.copy()
    env["PATH"] = f"{tmp_path}:{env['PATH']}"
    env["SAFEPLANE_TEST_DOCKER_CALLS"] = str(capture)
    result = subprocess.run(
        [str(ROOT / "scripts/safeplane"), *args],
        cwd=ROOT,
        env=env,
        text=True,
        capture_output=True,
        check=False,
    )
    calls = [json.loads(line) for line in capture.read_text().splitlines()]
    return result, calls


def test_launcher_executes_network_commands_only_in_cli_connector(tmp_path: Path) -> None:
    result, calls = run_launcher(tmp_path, "chat", "hello world")
    assert result.returncode == 0
    assert len(calls) == 2
    assert calls[0] == ["image", "inspect", "safeplane-cli-connector:latest"]
    assert calls[1][-7:] == [
        "run",
        "--rm",
        "--no-deps",
        "-T",
        "cli-connector",
        "chat",
        "hello world",
    ]
    launcher = (ROOT / "scripts/safeplane").read_text(encoding="utf-8")
    assert "SAFEPLANE_HARNESS_URL" not in launcher
    assert "curl" not in launcher
    assert "/connector/" not in launcher


def test_launcher_builds_cli_image_when_missing(tmp_path: Path) -> None:
    result, calls = run_launcher(tmp_path, "workflows", image_exists=False)
    assert result.returncode == 0
    assert calls[0] == ["image", "inspect", "safeplane-cli-connector:latest"]
    assert calls[1][-2:] == ["build", "cli-connector"]
    assert calls[2][-2:] == ["cli-connector", "workflows"]
    assert result.stderr == ""


def test_legacy_safeplane_chat_is_only_a_compatibility_launcher() -> None:
    text = (ROOT / "scripts/safeplane-chat").read_text(encoding="utf-8")
    assert "deprecated" in text
    assert 'exec "$SCRIPT_DIR/safeplane" "$@"' in text
    assert "curl" not in text
    assert "SAFEPLANE_HARNESS_URL" not in text
