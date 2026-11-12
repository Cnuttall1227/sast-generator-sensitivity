import os
import re
import logging
import subprocess

from slack_bolt import App
from slack_bolt.adapter.socket_mode import SocketModeHandler

SLACK_BOT_TOKEN = os.environ["SLACK_BOT_TOKEN"]
SLACK_APP_TOKEN = os.environ["SLACK_APP_TOKEN"]
KUBE_CONTEXT = os.environ.get("CHATOPS_KUBE_CONTEXT", "staging")
ALLOWED_NAMESPACES = {"web", "payments", "batch"}
ALLOWED_CHANNELS = set(filter(None, os.environ.get("CHATOPS_CHANNELS", "").split(",")))
OPERATOR_GROUP_MEMBERS = set(filter(None, os.environ.get("CHATOPS_OPERATORS", "").split(",")))
POD_PATTERN = re.compile(r"^[a-z0-9]([-a-z0-9.]{0,251}[a-z0-9])?$")
MAX_TAIL = 500
COMMAND_TIMEOUT = 30

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger("k8s-chatops")

app = App(token=SLACK_BOT_TOKEN)

HELP_TEXT = (
    "*Usage:* `/k8s <command> <namespace> [args]`\n"
    "• `pods <namespace>` – list pods\n"
    "• `logs <namespace> <pod> [lines]` – tail pod logs\n"
    "• `restart <namespace> <deployment>` – rolling restart (operators only)"
)


def kubectl(*args):
    result = subprocess.run(
        ["kubectl", "--context", KUBE_CONTEXT, *args],
        capture_output=True, text=True, timeout=COMMAND_TIMEOUT,
    )
    output = result.stdout if result.returncode == 0 else result.stderr
    return result.returncode, output.strip()


def list_pods(namespace):
    code, output = kubectl(
        "get", "pods", "-n", namespace,
        "-o", "custom-columns=NAME:.metadata.name,STATUS:.status.phase",
    )
    return output if code == 0 else f"Error: {output}"


def tail_logs(namespace, pod, lines):
    if namespace not in ALLOWED_NAMESPACES:
        return "Error: namespace not allowed"
    if not POD_PATTERN.fullmatch(pod):
        return "Error: invalid pod name"
    lines = max(1, min(int(lines), MAX_TAIL))
    code, output = kubectl(
        "logs", pod,
        "-n", namespace,
        f"--tail={lines}",
        "--timestamps",
    )
    if code != 0:
        return f"Error: {output}"
    trimmed = "\n".join(line[:300] for line in output.splitlines())
    return trimmed or "(no output)"


def restart_deployment(namespace, deployment):
    if not re.fullmatch(r"[a-z0-9]([-a-z0-9]{0,61}[a-z0-9])?", deployment):
        return "Error: invalid deployment name"
    code, output = kubectl("rollout", "restart", f"deployment/{deployment}", "-n", namespace)
    return output if code == 0 else f"Error: {output}"


def as_code_block(text, limit=3500):
    if len(text) > limit:
        text = "…" + text[-limit:]
    return f"```{text}```"


@app.command("/k8s")
def handle_k8s(ack, respond, command):
    ack()
    user = command.get("user_id", "")
    channel = command.get("channel_id", "")
    if ALLOWED_CHANNELS and channel not in ALLOWED_CHANNELS:
        respond("This command is not enabled in this channel.")
        return
    parts = (command.get("text") or "").split()
    if len(parts) < 2:
        respond(HELP_TEXT)
        return
    action, namespace, args = parts[0].lower(), parts[1], parts[2:]
    if namespace not in ALLOWED_NAMESPACES:
        respond(f"Namespace `{namespace}` is not available here.")
        return
    log.info("User %s ran %s in %s", user, action, namespace)
    try:
        if action == "pods":
            respond(as_code_block(list_pods(namespace)))
        elif action == "logs" and args:
            lines = min(int(args[1]), MAX_TAIL) if len(args) > 1 and args[1].isdigit() else 100
            respond(as_code_block(tail_logs(namespace, args[0], lines)))
        elif action == "restart" and args:
            if user not in OPERATOR_GROUP_MEMBERS:
                respond("Only operators can restart deployments.")
                return
            respond(restart_deployment(namespace, args[0]))
        else:
            respond(HELP_TEXT)
    except subprocess.TimeoutExpired:
        respond("The command timed out.")


@app.event("app_mention")
def handle_mention(say):
    say(HELP_TEXT)


if __name__ == "__main__":
    log.info("Starting k8s ChatOps bot for context %s", KUBE_CONTEXT)
    SocketModeHandler(app, SLACK_APP_TOKEN).start()