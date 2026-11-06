"""The action release ci.yml pins: its tree, its harness and its archive, checksums verified.

Immutable, so it is fetched once into `target/report-job`. The harness ships at the same tag, so a
pin bump brings the harness that matches it.
"""

import hashlib
import importlib.util
import io
import platform
import shutil
import tarfile
import tempfile
import urllib.request
from pathlib import Path
from types import ModuleType
from typing import NamedTuple

import yaml

ROOT = Path(__file__).resolve().parents[3]
ACTION = "nickderobertis/onebudgetspec-github-action"
TARGETS = {
    ("Linux", "x86_64"): "x86_64-unknown-linux-gnu",
    ("Linux", "aarch64"): "aarch64-unknown-linux-gnu",
    ("Darwin", "arm64"): "aarch64-apple-darwin",
}


class Released(NamedTuple):
    tag: str
    tree: Path
    archive: Path
    declared: dict
    harness: ModuleType


def workflow() -> dict:
    return yaml.safe_load(
        (ROOT / ".github/workflows/ci.yml").read_text(encoding="utf-8")
    )


def action_step(document: dict) -> dict:
    steps = document["jobs"]["budgets"]["steps"]
    uses = [step for step in steps if step.get("uses", "").startswith(f"{ACTION}@")]
    assert len(uses) == 1, f"the budgets job must use the action once: {steps}"
    return uses[0]


def _get(url: str) -> bytes:
    with urllib.request.urlopen(url, timeout=120) as response:
        return response.read()


def _fetch(tag: str, directory: Path, archive_name: str) -> None:
    """Everything or nothing: a partial fetch never passes as the release.

    Nx runs both of this release's test projects at once, so on a cold `target` two fetches race:
    each builds in a directory of its own, and whichever publishes second keeps the first's tree,
    which is the same immutable release.
    """
    releases = f"https://github.com/{ACTION}/releases/download/{tag}"
    directory.parent.mkdir(parents=True, exist_ok=True)
    partial = Path(tempfile.mkdtemp(dir=directory.parent, prefix=f"{directory.name}."))
    try:
        source = _get(f"https://codeload.github.com/{ACTION}/tar.gz/refs/tags/{tag}")
        with tarfile.open(fileobj=io.BytesIO(source)) as archive:
            for member in archive.getmembers():
                member.name = member.name.split("/", 1)[-1]
                archive.extract(member, partial, filter="data")
        sums = _get(f"{releases}/SHA256SUMS").decode()
        assets = {
            name: _get(f"{releases}/{name}") for name in (archive_name, "action.yml")
        }
        for name, body in assets.items():
            listed = f"{hashlib.sha256(body).hexdigest()}  {name}"
            assert listed in sums.splitlines(), (
                f"{name} is not what release {tag} lists"
            )
        assert assets["action.yml"] == (partial / "action.yml").read_bytes()
        (partial / "dist").mkdir()
        (partial / "dist" / archive_name).write_bytes(assets[archive_name])
        try:
            partial.rename(directory)
        except OSError:
            if not directory.is_dir():
                raise
    finally:
        shutil.rmtree(partial, ignore_errors=True)


def load() -> Released:
    tag = action_step(workflow())["uses"].split("@", 1)[1]
    version = tag.removeprefix("v")
    target = TARGETS[(platform.system(), platform.machine())]
    archive_name = f"onebudgetspec-github-action-{version}-{target}.tar.gz"
    tree = ROOT / "target" / "report-job" / f"action-{tag}"
    if not tree.is_dir():
        _fetch(tag, tree, archive_name)
    spec = importlib.util.spec_from_file_location(
        "released_action_harness", tree / "tests" / "action-harness" / "harness.py"
    )
    assert spec is not None and spec.loader is not None
    harness = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(harness)
    # The harness builds this from source for the action's own tests; a consumer gets the release.
    archive = tree / "dist" / archive_name
    harness._cached["archive"] = archive
    declared = yaml.safe_load((tree / "action.yml").read_text(encoding="utf-8"))
    return Released(tag, tree, archive, declared, harness)
