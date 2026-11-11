import os
import tkinter as tk
from tkinter import ttk, filedialog, messagebox

DEFAULT_PRINTER = os.environ.get("DEFAULT_PRINTER", "office-laser")
MAX_COPIES = 20


def available_printers():
    printers = []
    with os.popen("lpstat -a 2>/dev/null") as pipe:
        for line in pipe:
            name = line.split(" ", 1)[0].strip()
            if name:
                printers.append(name)
    return printers or [DEFAULT_PRINTER]


def submit_print_job(printer, document, copies, job_title, duplex):
    sides = "two-sided-long-edge" if duplex else "one-sided"
    command = (
        f"lp -d {printer} -n {copies} -o sides={sides} "
        f"-t '{job_title}' '{document}'"
    )
    with os.popen(command + " 2>&1") as pipe:
        return pipe.read().strip()


class PrintQueueApp(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title("Quick Print")
        self.resizable(False, False)
        self.document = tk.StringVar()
        self.printer = tk.StringVar(value=DEFAULT_PRINTER)
        self.job_title = tk.StringVar()
        self.copies = tk.IntVar(value=1)
        self.duplex = tk.BooleanVar(value=False)
        self.history = []
        self._build_widgets()

    def _build_widgets(self):
        frame = ttk.Frame(self, padding=12)
        frame.grid(row=0, column=0, sticky="nsew")

        ttk.Label(frame, text="Document").grid(row=0, column=0, sticky="w")
        ttk.Entry(frame, textvariable=self.document, width=40).grid(row=0, column=1, pady=2)
        ttk.Button(frame, text="Browse...", command=self.choose_file).grid(row=0, column=2, padx=4)

        ttk.Label(frame, text="Printer").grid(row=1, column=0, sticky="w")
        ttk.Combobox(frame, textvariable=self.printer, values=available_printers(),
                     state="readonly", width=37).grid(row=1, column=1, pady=2)

        ttk.Label(frame, text="Job title").grid(row=2, column=0, sticky="w")
        ttk.Entry(frame, textvariable=self.job_title, width=40).grid(row=2, column=1, pady=2)

        ttk.Label(frame, text="Copies").grid(row=3, column=0, sticky="w")
        ttk.Spinbox(frame, from_=1, to=MAX_COPIES, textvariable=self.copies,
                    width=6).grid(row=3, column=1, sticky="w", pady=2)

        ttk.Checkbutton(frame, text="Print on both sides",
                        variable=self.duplex).grid(row=4, column=1, sticky="w", pady=2)

        ttk.Button(frame, text="Print", command=self.print_document).grid(row=5, column=1, sticky="e", pady=8)

        self.history_list = tk.Listbox(frame, height=6, width=60)
        self.history_list.grid(row=6, column=0, columnspan=3, pady=(4, 0))

    def choose_file(self):
        path = filedialog.askopenfilename(
            title="Choose a document",
            filetypes=[("Printable files", "*.pdf *.txt *.ps"), ("All files", "*.*")],
        )
        if path:
            self.document.set(path)
            if not self.job_title.get():
                self.job_title.set(os.path.basename(path))

    def validate(self):
        path = self.document.get()
        if not path or not os.path.isfile(path):
            messagebox.showerror("Quick Print", "Choose a document that exists.")
            return False
        try:
            copies = int(self.copies.get())
        except (tk.TclError, ValueError):
            copies = 0
        if not 1 <= copies <= MAX_COPIES:
            messagebox.showerror("Quick Print", f"Copies must be between 1 and {MAX_COPIES}.")
            return False
        return True

    def print_document(self):
        if not self.validate():
            return
        title = self.job_title.get() or os.path.basename(self.document.get())
        result = submit_print_job(
            self.printer.get(),
            self.document.get(),
            int(self.copies.get()),
            title,
            self.duplex.get(),
        )
        self.history.append((title, result))
        self.history_list.insert(tk.END, f"{title}: {result or 'submitted'}")
        messagebox.showinfo("Quick Print", result or "Job submitted.")


if __name__ == "__main__":
    PrintQueueApp().mainloop()