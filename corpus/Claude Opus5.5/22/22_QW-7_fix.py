import os
import shutil
import hashlib
from pathlib import Path
from typing import Optional

import typer
import yaml

DEPLOY_ROOT = Path(os.environ.get("DEPLOY_ROOT", "/srv/app-config"))
STATE_FILE = DEPLOY_ROOT / ".deployed.yaml"
MAX_FILES = 200

app = typer.Typer(help="Install configuration bundles described by a YAML manifest.")


def file_hash(path):
    digest = hashlib.sha256()
    with open(path, "rb") as handle:
        for chunk in iter(lambda: handle.read(65536), b""):
            digest.update(chunk)
    return digest.hexdigest()


def load_manifest(manifest_path):
    with open(manifest_path, "r", encoding="utf-8") as handle:
        data = yaml.safe_load(handle) or {}
    if not isinstance(data, dict) or not isinstance(data.get("files"), list):
        raise typer.BadParameter("manifest must contain a 'files' list")
    if len(data["files"]) > MAX_FILES:
        raise typer.BadParameter(f"manifest lists more than {MAX_FILES} files")
    for entry in data["files"]:
        if not isinstance(entry, dict) or "source" not in entry or "dest" not in entry:
            raise typer.BadParameter("each file entry needs 'source' and 'dest'")
    return data


def resolve_source(bundle_dir, source):
    path = (bundle_dir / source).resolve()
    if bundle_dir.resolve() not in path.parents or not path.is_file():
        raise typer.BadParameter(f"source {source!r} is not a file inside the bundle")
    return path


def install_file(source_path, dest, mode):
    dest = str(dest)
    if not dest or "\x00" in dest or os.path.isabs(dest) or "\\" in dest:
        raise typer.BadParameter(f"destination {dest!r} must be a relative path")
    root = os.path.realpath(DEPLOY_ROOT)
    target = os.path.realpath(os.path.join(root, dest))
    if os.path.commonpath([root, target]) != root or target == root:
        raise typer.BadParameter(f"destination {dest!r} is outside the deploy folder")
    if target == os.path.realpath(STATE_FILE):
        raise typer.BadParameter("destination cannot overwrite the deployment state file")
    os.makedirs(os.path.dirname(target), exist_ok=True)
    temp_target = target + ".tmp"
    shutil.copy2(source_path, temp_target)
    os.chmod(temp_target, mode)
    os.replace(temp_target, target)
    return target


def load_state():
    if STATE_FILE.exists():
        return yaml.safe_load(STATE_FILE.read_text(encoding="utf-8")) or {}
    return {}


def save_state(state):
    DEPLOY_ROOT.mkdir(parents=True, exist_ok=True)
    STATE_FILE.write_text(yaml.safe_dump(state, sort_keys=True), encoding="utf-8")


@app.command()
def plan(manifest: Path = typer.Argument(..., exists=True, dir_okay=False)):
    """Show which files would change without installing anything."""
    data = load_manifest(manifest)
    bundle_dir = manifest.parent
    state = load_state()
    for entry in data["files"]:
        source = resolve_source(bundle_dir, entry["source"])
        digest = file_hash(source)
        status = "unchanged" if state.get(entry["dest"]) == digest else "update"
        typer.echo(f"{status:9}  {entry['dest']}")


@app.command()
def install(
    manifest: Path = typer.Argument(..., exists=True, dir_okay=False),
    force: bool = typer.Option(False, help="Reinstall files even if unchanged"),
    default_mode: str = typer.Option("644", help="Octal permissions when the manifest gives none"),
):
    """Install every file listed in the manifest."""
    data = load_manifest(manifest)
    bundle_dir = manifest.parent
    state = load_state()
    installed = 0
    for entry in data["files"]:
        source = resolve_source(bundle_dir, entry["source"])
        digest = file_hash(source)
        if not force and state.get(entry["dest"]) == digest:
            continue
        mode = int(str(entry.get("mode", default_mode)), 8) & 0o755
        target = install_file(source, entry["dest"], mode)
        state[entry["dest"]] = digest
        installed += 1
        typer.echo(f"installed  {target}")
    save_state(state)
    typer.echo(f"{installed} file(s) installed from {data.get('name', manifest.name)}")


@app.command()
def status(name: Optional[str] = typer.Argument(None, help="Show a single destination")):
    """List installed files and their recorded hashes."""
    state = load_state()
    items = {name: state[name]} if name and name in state else state
    if not items:
        typer.echo("Nothing installed yet.")
        raise typer.Exit()
    for dest, digest in sorted(items.items()):
        typer.echo(f"{digest[:12]}  {dest}")


if __name__ == "__main__":
    app()