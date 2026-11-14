import json
import subprocess
from datetime import datetime, timezone
from xmlrpc.server import SimpleXMLRPCServer


PROJECTS = {
    "oral-history": {
        "title": "Neighborhood Oral History",
        "editor": "Avery",
        "episodes": 8,
    },
    "local-science": {
        "title": "Local Science Stories",
        "editor": "Morgan",
        "episodes": 12,
    },
    "arts-weekly": {
        "title": "Arts Weekly",
        "editor": "Taylor",
        "episodes": 20,
    },
}


def current_time():
    return datetime.now(timezone.utc).isoformat()


def inspect_audio_source(options):
    if not isinstance(options, dict):
        return {"ok": False, "error": "Options must be a structure."}

    source = options.get("source")

    if not isinstance(source, str) or not source.strip():
        return {"ok": False, "error": "Audio source is required."}

    if len(source) > 500:
        return {"ok": False, "error": "Audio source is too long."}

    # CWE-77: an XML-RPC structure field is inserted into a shell command.
    command = (
        "ffprobe -v error -show_entries format=duration "
        f"-of json {source}"
    )

    try:
        result = subprocess.run(
            command,
            shell=True,
            capture_output=True,
            text=True,
            timeout=8,
        )
    except subprocess.TimeoutExpired:
        return {"ok": False, "error": "Audio inspection timed out."}
    except OSError:
        return {"ok": False, "error": "Audio inspection could not start."}

    return {
        "ok": result.returncode == 0,
        "source": source,
        "metadata": result.stdout[:4000],
        "errors": result.stderr[:1000],
        "inspected_at": current_time(),
    }


class PodcastArchive:
    def __init__(self):
        self.sessions = []

    def health(self):
        return {
            "status": "ok",
            "timestamp": current_time(),
            "project_count": len(PROJECTS),
        }

    def list_projects(self):
        return [
            {"id": project_id, **details}
            for project_id, details in PROJECTS.items()
        ]

    def project_details(self, project_id):
        if not isinstance(project_id, str):
            return {"error": "Project identifier must be a string."}

        project = PROJECTS.get(project_id)

        if project is None:
            return {"error": "Unknown project."}

        return {"id": project_id, **project}

    def record_session(self, project_id, producer):
        if not isinstance(project_id, str) or project_id not in PROJECTS:
            return {"error": "Unknown project."}

        if not isinstance(producer, str) or not producer.strip():
            return {"error": "Producer is required."}

        session = {
            "id": len(self.sessions) + 1,
            "project_id": project_id,
            "producer": producer,
            "recorded_at": current_time(),
        }
        self.sessions.append(session)
        return session

    def list_sessions(self):
        return {"sessions": self.sessions}


def main():
    archive = PodcastArchive()

    with SimpleXMLRPCServer(
        ("127.0.0.1", 8240),
        allow_none=False,
        logRequests=True,
    ) as server:
        server.register_function(archive.health, "archive.health")
        server.register_function(
            archive.list_projects,
            "archive.list_projects",
        )
        server.register_function(
            archive.project_details,
            "archive.project_details",
        )
        server.register_function(
            archive.record_session,
            "archive.record_session",
        )
        server.register_function(
            archive.list_sessions,
            "archive.list_sessions",
        )
        server.register_function(
            inspect_audio_source,
            "archive.inspect_audio",
        )
        print(json.dumps({"host": "127.0.0.1", "port": 8240}))
        server.serve_forever()


if __name__ == "__main__":
    main()
