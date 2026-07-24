from __future__ import annotations

import re
from pathlib import Path

import yaml


ROOT = Path(__file__).resolve().parents[2]
CURRENT_MARKDOWN = [
    ROOT / "README.md",
    *[
        path
        for path in sorted((ROOT / "docs").rglob("*.md"))
        if "history" not in path.parts and "adr" not in path.parts
    ],
]
LINK = re.compile(r"\[[^\]]+\]\(([^)]+)\)")
COMMAND_PATH = re.compile(
    r"(?<![A-Za-z0-9_.-])(\./scripts/[A-Za-z0-9._-]+|tests/scripts/[A-Za-z0-9._-]+)"
)
MAKE_TARGET = re.compile(r"(?m)^([A-Za-z0-9][A-Za-z0-9_-]*):(?:\s|$)")
DOCUMENTED_MAKE = re.compile(r"(?m)^\s*make\s+([A-Za-z0-9][A-Za-z0-9_-]*)\b")
PROMPT_REF = re.compile(r"`(developer\.[a-z.]+)@(v\d+)`")


def current_text() -> str:
    return "\n".join(path.read_text(encoding="utf-8") for path in CURRENT_MARKDOWN)


def github_anchor(heading: str) -> str:
    value = re.sub(r"[`*_]", "", heading.strip().lower())
    value = re.sub(r"[^a-z0-9 _-]", "", value)
    return re.sub(r"[ _]+", "-", value).strip("-")


def headings(path: Path) -> set[str]:
    anchors: set[str] = set()
    for line in path.read_text(encoding="utf-8").splitlines():
        match = re.match(r"^#{1,6}\s+(.+?)\s*$", line)
        if match:
            anchors.add(github_anchor(match.group(1)))
    return anchors


def resolve_link(source: Path, raw_link: str) -> tuple[Path, str | None] | None:
    if raw_link.startswith(("http://", "https://", "mailto:")):
        return None
    target_text, _, anchor = raw_link.partition("#")
    if not target_text:
        target = source
    elif target_text.startswith("/"):
        target = ROOT / target_text.lstrip("/")
    else:
        target = source.parent / target_text
    return target.resolve(), anchor or None


def test_readme_and_current_document_links_resolve() -> None:
    failures: list[str] = []
    for source in CURRENT_MARKDOWN:
        for raw_link in LINK.findall(source.read_text(encoding="utf-8")):
            resolved = resolve_link(source, raw_link)
            if resolved is None:
                continue
            target, anchor = resolved
            if not target.exists():
                failures.append(f"{source.relative_to(ROOT)} -> {raw_link}: missing file")
                continue
            if anchor and target.suffix == ".md" and anchor not in headings(target):
                failures.append(f"{source.relative_to(ROOT)} -> {raw_link}: missing heading")
    assert failures == []


def test_documented_script_and_make_commands_exist() -> None:
    failures: list[str] = []
    make_targets = set(MAKE_TARGET.findall((ROOT / "Makefile").read_text(encoding="utf-8")))
    for source in CURRENT_MARKDOWN:
        text = source.read_text(encoding="utf-8")
        for command_path in COMMAND_PATH.findall(text):
            relative = command_path[2:] if command_path.startswith("./") else command_path
            target = ROOT / relative
            if not target.is_file():
                failures.append(f"{source.relative_to(ROOT)}: missing {relative}")
            elif not target.stat().st_mode & 0o111:
                failures.append(f"{source.relative_to(ROOT)}: not executable {relative}")
        for target in DOCUMENTED_MAKE.findall(text):
            if target not in make_targets:
                failures.append(f"{source.relative_to(ROOT)}: missing make target {target}")
    assert failures == []


def test_documented_operator_workflows_match_registry() -> None:
    registry = yaml.safe_load((ROOT / "safeplane.yaml").read_text(encoding="utf-8"))
    exposed = {
        entrypoint
        for entrypoint, config in registry["entrypoints"].items()
        if config.get("operator_facing")
    }
    assert exposed == {"chat", "assistant", "develop"}

    readme = (ROOT / "README.md").read_text(encoding="utf-8")
    operations = (ROOT / "docs" / "scripts.md").read_text(encoding="utf-8")
    for entrypoint in exposed:
        assert f"safeplane {entrypoint}" in readme
        assert f"safeplane {entrypoint}" in operations
        assert f"/{entrypoint}" in operations


def test_developer_agent_and_prompt_names_match_contract() -> None:
    workflow = yaml.safe_load(
        (ROOT / "workflows" / "developer" / "workflow.yaml").read_text(
            encoding="utf-8"
        )
    )
    manifest = yaml.safe_load(
        (ROOT / "prompts" / "developer" / "manifest.yaml").read_text(
            encoding="utf-8"
        )
    )
    document = (ROOT / "docs" / "developer-pipeline.md").read_text(encoding="utf-8")

    documented_agents = set(
        re.findall(r"(?m)^\| `([a-z-]+)` \| `developer\.", document)
    )
    assert documented_agents == set(workflow["agents"])

    manifest_prompts = {
        (item["id"], item["version"]) for item in manifest["prompts"].values()
    }
    documented_prompts = set(PROMPT_REF.findall(document))
    assert documented_prompts == manifest_prompts
    for item in manifest["prompts"].values():
        assert (ROOT / item["path"]).is_file()


def test_documented_service_matrix_matches_compose_services() -> None:
    compose_files = (
        "docker-compose.yml",
        "docker-compose.developer.yml",
        "docker-compose.telegram.yml",
        "docker-compose.github-mock.yml",
    )
    actual: set[str] = set()
    for name in compose_files:
        compose = yaml.safe_load((ROOT / name).read_text(encoding="utf-8"))
        actual.update(compose.get("services", {}))

    document = (ROOT / "docs" / "security" / "runtime-boundaries.md").read_text(
        encoding="utf-8"
    )
    documented = set(re.findall(r"(?m)^\| `([a-z0-9-]+)` \|", document))
    assert documented == actual


def test_current_docs_do_not_reintroduce_stale_or_private_product_claims() -> None:
    text = current_text()
    lowered = text.lower()
    stale_claims = (
        "the assistant cannot write calendar entries yet",
        "telegram cannot write calendar entries yet",
        "there is no calendar mcp server yet",
        "no real run manager yet",
        "developer workspace tools will build on this later",
        "future single-pass developer workflow",
        "m" + "vp 0 is current",
    )
    for claim in stale_claims:
        assert claim not in lowered

    assert re.search(r"(?i)\bmvp\s*\d", text) is None
    forbidden_targets = ("daily" + "dash", "sil" + "ver")
    for term in forbidden_targets:
        assert re.search(rf"(?i)\b{re.escape(term)}\b", text) is None

    readme = (ROOT / "README.md").read_text(encoding="utf-8")
    assert "/Users/" not in readme
    assert re.search(r"/home/[A-Za-z0-9._-]+", readme) is None
    assert "https://github.com/" not in readme


def test_readme_keeps_explicit_current_limitations() -> None:
    readme = (ROOT / "README.md").read_text(encoding="utf-8")
    assert "## Known limitations" in readme
    assert "MacBook" in readme and "VPS" in readme
    assert "single-pass" in readme
    assert "never merges" in readme
    assert "backup-and-restore" in readme
