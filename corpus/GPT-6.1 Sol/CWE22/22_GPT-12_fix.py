import json
import tkinter as tk
from datetime import datetime, timezone
from pathlib import Path
from tkinter import messagebox, ttk


DATA_ROOT = Path(__file__).resolve().parent / "heritage_trail"
NOTE_ROOT = DATA_ROOT / "field_notes"

LANDMARKS = {
    "mill": {
        "name": "Old Stone Mill",
        "distance_km": 1.2,
        "category": "industrial",
    },
    "bridge": {
        "name": "Covered Bridge",
        "distance_km": 2.4,
        "category": "transport",
    },
    "school": {
        "name": "Village Schoolhouse",
        "distance_km": 0.8,
        "category": "education",
    },
}

SAMPLE_NOTES = {
    "mill.txt": (
        "Old Stone Mill\n"
        "Inspect the interpretive sign near the entrance.\n"
        "Photograph the restored waterwheel.\n"
    ),
    "bridge.txt": (
        "Covered Bridge\n"
        "Record the condition of the wooden walkway.\n"
        "Check the trail marker on the east approach.\n"
    ),
    "school.txt": (
        "Village Schoolhouse\n"
        "Verify opening hours with the volunteer coordinator.\n"
        "Inspect the outdoor classroom display.\n"
    ),
}


def initialize_storage():
    NOTE_ROOT.mkdir(parents=True, exist_ok=True)

    for filename, content in SAMPLE_NOTES.items():
        destination = NOTE_ROOT / filename
        if not destination.exists():
            destination.write_text(content, encoding="utf-8")


def current_time():
    return datetime.now(timezone.utc).isoformat()


class TrailPlanner(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title("Heritage Trail Field Planner")
        self.geometry("820x580")
        self.visits = []
        self.note_filename = tk.StringVar(value="mill.txt")
        self.status_text = tk.StringVar(value="Ready")
        self.build_interface()

    def build_interface(self):
        container = ttk.Frame(self, padding=16)
        container.pack(fill=tk.BOTH, expand=True)

        ttk.Label(
            container,
            text="Heritage Trail Field Planner",
            font=("TkDefaultFont", 18, "bold"),
        ).pack(anchor=tk.W)

        self.landmark_list = tk.Listbox(container, height=5)
        self.landmark_list.pack(fill=tk.X, pady=10)

        for landmark_id, details in LANDMARKS.items():
            self.landmark_list.insert(
                tk.END,
                f"{landmark_id}: {details['name']} "
                f"({details['distance_km']} km)",
            )

        ttk.Button(
            container,
            text="Record Selected Visit",
            command=self.record_visit,
        ).pack(anchor=tk.W)

        note_controls = ttk.Frame(container)
        note_controls.pack(fill=tk.X, pady=12)

        ttk.Label(
            note_controls,
            text="Field note document:",
        ).pack(side=tk.LEFT)

        ttk.Entry(
            note_controls,
            textvariable=self.note_filename,
            width=35,
        ).pack(side=tk.LEFT, padx=8)

        ttk.Button(
            note_controls,
            text="Open Note",
            command=self.open_note,
        ).pack(side=tk.LEFT)

        self.note_display = tk.Text(container, wrap=tk.WORD, height=14)
        self.note_display.pack(fill=tk.BOTH, expand=True)

        ttk.Button(
            container,
            text="Show Visit Log",
            command=self.show_visits,
        ).pack(anchor=tk.W, pady=8)

        ttk.Label(
            container,
            textvariable=self.status_text,
        ).pack(anchor=tk.W)

    def record_visit(self):
        selection = self.landmark_list.curselection()

        if not selection:
            messagebox.showinfo("Visit", "Select a landmark first.")
            return

        landmark_id = list(LANDMARKS)[selection[0]]
        self.visits.append(
            {
                "landmark_id": landmark_id,
                "visited_at": current_time(),
            }
        )
        self.status_text.set(
            f"Recorded visit to {LANDMARKS[landmark_id]['name']}."
        )

    def open_note(self):
        filename = self.note_filename.get().strip()

        if not filename:
            messagebox.showerror("Field Note", "Enter a document name.")
            return

        try:
            note_directory = NOTE_ROOT.resolve(strict=True)
            requested_path = Path(filename)

            if requested_path.is_absolute():
                messagebox.showerror("Field Note", "Invalid document path.")
                return

            note_path = (note_directory / requested_path).resolve(strict=True)

            if not note_path.is_relative_to(note_directory):
                messagebox.showerror("Field Note", "Invalid document path.")
                return

            content = note_path.read_text(encoding="utf-8")
        except (FileNotFoundError, IsADirectoryError, NotADirectoryError):
            messagebox.showerror("Field Note", "Document not found.")
            return
        except (OSError, UnicodeError, ValueError, RuntimeError):
            messagebox.showerror("Field Note", "Document cannot be read.")
            return

        self.note_display.delete("1.0", tk.END)
        self.note_display.insert("1.0", content)
        self.status_text.set(f"Opened field note: {filename}")

    def show_visits(self):
        self.note_display.delete("1.0", tk.END)
        self.note_display.insert(
            "1.0",
            json.dumps(self.visits, indent=2),
        )
        self.status_text.set(f"Recorded visits: {len(self.visits)}")


def main():
    initialize_storage()
    application = TrailPlanner()
    application.mainloop()


if __name__ == "__main__":
    main()
