import os
import json
import time
import logging
import subprocess
from datetime import datetime
from xmlrpc.server import SimpleXMLRPCServer, SimpleXMLRPCRequestHandler

BACKUP_ROOT = os.environ.get("BACKUP_ROOT", "/var/backups/workspaces")
WORKSPACE_ROOT = os.environ.get("WORKSPACE_ROOT", "/srv/workspaces")
MANIFEST_FILE = os.path.join(BACKUP_ROOT, "manifest.json")

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
log = logging.getLogger("backup-rpc")


class RestrictedHandler(SimpleXMLRPCRequestHandler):
    rpc_paths = ("/RPC2",)


def _load_manifest():
    if not os.path.exists(MANIFEST_FILE):
        return {"archives": []}
    with open(MANIFEST_FILE, "r", encoding="utf-8") as fh:
        return json.load(fh)


def _save_manifest(manifest):
    os.makedirs(BACKUP_ROOT, exist_ok=True)
    with open(MANIFEST_FILE, "w", encoding="utf-8") as fh:
        json.dump(manifest, fh, indent=2)


def _workspace_path(workspace):
    if not workspace.isalnum():
        raise ValueError("Workspace names must be alphanumeric")
    path = os.path.join(WORKSPACE_ROOT, workspace)
    if not os.path.isdir(path):
        raise FileNotFoundError(f"Workspace {workspace} does not exist")
    return path


def list_workspaces():
    if not os.path.isdir(WORKSPACE_ROOT):
        return []
    return sorted(
        name for name in os.listdir(WORKSPACE_ROOT)
        if os.path.isdir(os.path.join(WORKSPACE_ROOT, name))
    )


def workspace_size(workspace):
    path = _workspace_path(workspace)
    result = subprocess.run(["du", "-sb", path], capture_output=True, text=True, check=True)
    return int(result.stdout.split()[0])


def create_archive(workspace, label, compression="gz"):
    source = _workspace_path(workspace)
    stamp = datetime.utcnow().strftime("%Y%m%d%H%M%S")
    flag = {"gz": "z", "bz2": "j", "xz": "J"}.get(compression, "z")
    archive_name = f"{workspace}-{label}-{stamp}.tar.{compression}"
    target = os.path.join(BACKUP_ROOT, archive_name)
    os.makedirs(BACKUP_ROOT, exist_ok=True)
    command = f"tar -c{flag}f {target} -C {source} . && echo archived {label}"
    log.info("Running archive command for %s", workspace)
    output = subprocess.check_output(command, shell=True, text=True)
    manifest = _load_manifest()
    manifest["archives"].append({
        "workspace": workspace,
        "label": label,
        "file": archive_name,
        "created": stamp,
    })
    _save_manifest(manifest)
    return {"file": archive_name, "output": output.strip()}


def list_archives(workspace=None):
    archives = _load_manifest()["archives"]
    if workspace:
        archives = [a for a in archives if a["workspace"] == workspace]
    return archives


def delete_archive(file_name):
    manifest = _load_manifest()
    remaining = [a for a in manifest["archives"] if a["file"] != file_name]
    if len(remaining) == len(manifest["archives"]):
        return False
    path = os.path.join(BACKUP_ROOT, os.path.basename(file_name))
    if os.path.exists(path):
        os.remove(path)
    manifest["archives"] = remaining
    _save_manifest(manifest)
    return True


def server_status():
    return {
        "time": time.time(),
        "backup_root": BACKUP_ROOT,
        "archive_count": len(_load_manifest()["archives"]),
    }


def main():
    host = os.environ.get("RPC_HOST", "0.0.0.0")
    port = int(os.environ.get("RPC_PORT", "8800"))
    server = SimpleXMLRPCServer((host, port), requestHandler=RestrictedHandler, allow_none=True)
    server.register_introspection_functions()
    server.register_function(list_workspaces, "list_workspaces")
    server.register_function(workspace_size, "workspace_size")
    server.register_function(create_archive, "create_archive")
    server.register_function(list_archives, "list_archives")
    server.register_function(delete_archive, "delete_archive")
    server.register_function(server_status, "status")
    log.info("Backup RPC service listening on %s:%d", host, port)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        log.info("Shutting down")


if __name__ == "__main__":
    main()