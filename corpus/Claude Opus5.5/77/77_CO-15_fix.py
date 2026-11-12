import os
import cmd
import sys
import shlex
import subprocess
import xml.etree.ElementTree as ET

LIBVIRT_URI = os.environ.get("SNAPSHELL_URI", "qemu:///system")
MANAGED_PREFIX = os.environ.get("SNAPSHELL_PREFIX", "lab-")
MAX_DESCRIPTION = 200


def virsh(*args):
    result = subprocess.run(
        ["virsh", "--connect", LIBVIRT_URI, *args],
        capture_output=True, text=True, timeout=120,
    )
    if result.returncode != 0:
        raise RuntimeError(result.stderr.strip() or "virsh failed")
    return result.stdout


def managed_domains():
    names = virsh("list", "--all", "--name").split()
    return [name for name in names if name.startswith(MANAGED_PREFIX)]


def snapshot_names(domain):
    return virsh("snapshot-list", domain, "--name").split()


def snapshot_description(domain, snapshot):
    xml_text = virsh("snapshot-dumpxml", domain, snapshot)
    node = ET.fromstring(xml_text).find("description")
    return node.text if node is not None and node.text else ""


def create_snapshot(domain, snapshot, description):
    if not domain.startswith(MANAGED_PREFIX) or domain.startswith("-"):
        raise ValueError("not a managed lab VM")
    if not snapshot or snapshot.startswith("-") or not snapshot.replace("-", "").replace("_", "").isalnum():
        raise ValueError("snapshot names may use letters, digits, - and _")
    description = description[:MAX_DESCRIPTION]
    if not description.isprintable():
        raise ValueError("description must not contain control characters")
    argv = [
        "virsh", "--connect", LIBVIRT_URI,
        "snapshot-create-as",
        "--domain", domain,
        "--name", snapshot,
        "--description", description,
        "--atomic",
    ]
    pid = os.fork()
    if pid == 0:
        try:
            os.execvp("virsh", argv)
        finally:
            os._exit(127)
    _, status = os.waitpid(pid, 0)
    return os.waitstatus_to_exitcode(status)


class SnapShell(cmd.Cmd):
    intro = "Lab snapshot shell. Type help or ? to list commands."
    prompt = "(snap) "

    def check_domain(self, domain):
        if domain not in managed_domains():
            print(f"error: {domain} is not a managed lab VM")
            return False
        return True

    def do_vms(self, arg):
        """vms - list managed lab VMs"""
        for name in managed_domains():
            print(name)

    def do_list(self, arg):
        """list <vm> - list snapshots for a VM"""
        parts = shlex.split(arg)
        if len(parts) != 1 or not self.check_domain(parts[0]):
            return
        for snap in snapshot_names(parts[0]):
            print(f"{snap:30} {snapshot_description(parts[0], snap)}")

    def do_snap(self, arg):
        """snap <vm> <name> [description...] - create a snapshot"""
        parts = shlex.split(arg)
        if len(parts) < 2:
            print("usage: snap <vm> <name> [description...]")
            return
        domain, snapshot = parts[0], parts[1]
        description = " ".join(parts[2:])[:MAX_DESCRIPTION]
        if not self.check_domain(domain):
            return
        if not snapshot.replace("-", "").replace("_", "").isalnum():
            print("error: snapshot names may use letters, digits, - and _")
            return
        code = create_snapshot(domain, snapshot, description)
        print("created" if code == 0 else f"failed (exit {code})")

    def do_revert(self, arg):
        """revert <vm> <name> - revert a VM to a snapshot"""
        parts = shlex.split(arg)
        if len(parts) != 2 or not self.check_domain(parts[0]):
            print("usage: revert <vm> <name>")
            return
        if parts[1] not in snapshot_names(parts[0]):
            print("error: no such snapshot")
            return
        virsh("snapshot-revert", parts[0], parts[1])
        print("reverted")

    def do_delete(self, arg):
        """delete <vm> <name> - delete a snapshot"""
        parts = shlex.split(arg)
        if len(parts) != 2 or not self.check_domain(parts[0]):
            print("usage: delete <vm> <name>")
            return
        virsh("snapshot-delete", parts[0], parts[1])
        print("deleted")

    def onecmd(self, line):
        try:
            return super().onecmd(line)
        except (RuntimeError, ValueError, subprocess.TimeoutExpired) as exc:
            print(f"error: {exc}")
            return False

    def do_quit(self, arg):
        """quit - leave the shell"""
        return True

    do_EOF = do_quit


if __name__ == "__main__":
    if len(sys.argv) > 1:
        SnapShell().onecmd(" ".join(shlex.quote(a) for a in sys.argv[1:]))
    else:
        SnapShell().cmdloop()