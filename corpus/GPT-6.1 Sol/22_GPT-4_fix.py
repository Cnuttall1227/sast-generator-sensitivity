import argparse
import cmd
import json
from datetime import datetime, timezone
from pathlib import Path


DATA_ROOT = Path(__file__).resolve().parent / "observatory_data"
REPORT_ROOT = DATA_ROOT / "reports"

TELESCOPES = {
    "north": {
        "name": "North Dome",
        "aperture_cm": 60,
        "status": "available",
    },
    "south": {
        "name": "South Dome",
        "aperture_cm": 90,
        "status": "maintenance",
    },
    "roof": {
        "name": "Roof Telescope",
        "aperture_cm": 25,
        "status": "available",
    },
}

SAMPLE_REPORTS = {
    "north.txt": (
        "North Dome observation report\n"
        "Target: Jupiter\n"
        "Conditions: Clear skies, moderate seeing.\n"
    ),
    "south.txt": (
        "South Dome maintenance report\n"
        "Mirror alignment inspection scheduled.\n"
    ),
    "roof.txt": (
        "Roof Telescope observation report\n"
        "Target: Moon\n"
        "Conditions: Thin clouds, good visibility.\n"
    ),
}


def initialize_storage():
    REPORT_ROOT.mkdir(parents=True, exist_ok=True)

    for filename, content in SAMPLE_REPORTS.items():
        destination = REPORT_ROOT / filename
        if not destination.exists():
            destination.write_text(content, encoding="utf-8")


def timestamp():
    return datetime.now(timezone.utc).isoformat()


class ObservatoryConsole(cmd.Cmd):
    intro = "Observatory console. Type help to list commands."
    prompt = "observatory> "

    def __init__(self):
        super().__init__()
        self.reservations = []

    def do_telescopes(self, argument):
        """List telescopes: telescopes"""
        for telescope_id, details in TELESCOPES.items():
            print(
                f"{telescope_id}: {details['name']} "
                f"({details['aperture_cm']} cm), "
                f"{details['status']}"
            )

    def do_status(self, argument):
        """Display console status: status"""
        print(
            json.dumps(
                {
                    "timestamp": timestamp(),
                    "telescope_count": len(TELESCOPES),
                    "reservation_count": len(self.reservations),
                },
                indent=2,
            )
        )

    def do_reserve(self, argument):
        """Reserve a telescope: reserve <telescope_id> <observer_name>"""
        parts = argument.strip().split(maxsplit=1)

        if len(parts) != 2:
            print("Usage: reserve <telescope_id> <observer_name>")
            return

        telescope_id, observer_name = parts
        telescope = TELESCOPES.get(telescope_id)

        if telescope is None:
            print("Unknown telescope.")
            return

        if telescope["status"] != "available":
            print("This telescope is unavailable.")
            return

        reservation = {
            "id": len(self.reservations) + 1,
            "telescope_id": telescope_id,
            "observer": observer_name,
            "created_at": timestamp(),
        }
        self.reservations.append(reservation)
        print(f"Reservation {reservation['id']} created.")

    def do_reservations(self, argument):
        """List reservations: reservations"""
        print(json.dumps(self.reservations, indent=2))

    def do_report(self, argument):
        """Read an observation report: report <relative_filename>"""
        filename = argument.strip()

        if not filename:
            print("Usage: report <relative_filename>")
            return

        try:
            report_directory = REPORT_ROOT.resolve(strict=True)
            requested_path = Path(filename)

            if requested_path.is_absolute():
                print("Invalid report path.")
                return

            report_path = (report_directory / requested_path).resolve(
                strict=True
            )

            if not report_path.is_relative_to(report_directory):
                print("Invalid report path.")
                return

            content = report_path.read_text(encoding="utf-8")
        except (FileNotFoundError, IsADirectoryError, NotADirectoryError):
            print("Report not found.")
            return
        except (OSError, UnicodeError, ValueError, RuntimeError):
            print("Report cannot be read.")
            return

        print(content, end="" if content.endswith("\n") else "\n")

    def do_quit(self, argument):
        """Exit the console: quit"""
        print("Console closed.")
        return True

    def do_EOF(self, argument):
        """Exit the console with end-of-file."""
        print()
        return True

    def emptyline(self):
        pass


def main():
    parser = argparse.ArgumentParser(
        description="Interactive observatory reservation console."
    )
    parser.parse_args()
    initialize_storage()
    ObservatoryConsole().cmdloop()


if __name__ == "__main__":
    main()
