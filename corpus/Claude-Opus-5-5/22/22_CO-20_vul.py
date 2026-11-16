import os
import sys
import json
import shutil
from pathlib import Path

from PySide6.QtCore import Qt
from PySide6.QtGui import QPixmap
from PySide6.QtWidgets import (
    QApplication, QFileDialog, QHBoxLayout, QLabel, QListWidget, QMainWindow,
    QMessageBox, QPushButton, QVBoxLayout, QWidget,
)

SUPPORTED_IMAGES = {".png", ".jpg", ".jpeg", ".gif", ".webp"}


class ProjectError(Exception):
    pass


def load_project(project_file):
    with open(project_file, "r", encoding="utf-8") as handle:
        data = json.load(handle)
    slides = data.get("slides")
    if not isinstance(slides, list) or not slides:
        raise ProjectError("Project has no slides")
    for slide in slides:
        if not isinstance(slide, dict) or not isinstance(slide.get("image"), str):
            raise ProjectError("Every slide needs an 'image' entry")
    return {"title": str(data.get("title", Path(project_file).stem)), "slides": slides}


def resolve_asset(project_dir, image_ref):
    return os.path.join(project_dir, "assets", image_ref)


def export_slideshow(project_file, project, output_dir):
    project_dir = os.path.dirname(os.path.abspath(project_file))
    os.makedirs(output_dir, exist_ok=True)
    exported = []
    for index, slide in enumerate(project["slides"], start=1):
        source = resolve_asset(project_dir, slide["image"])
        if not os.path.isfile(source):
            raise ProjectError(f"Slide {index}: image not found ({slide['image']})")
        extension = Path(source).suffix.lower() or ".bin"
        target_name = f"slide-{index:03d}{extension}"
        shutil.copyfile(source, os.path.join(output_dir, target_name))
        exported.append({"file": target_name, "caption": str(slide.get("caption", ""))})
    with open(os.path.join(output_dir, "slides.json"), "w", encoding="utf-8") as handle:
        json.dump({"title": project["title"], "slides": exported}, handle, indent=2)
    return len(exported)


class SlideshowWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("Slideshow exporter")
        self.project_file = None
        self.project = None

        self.slide_list = QListWidget()
        self.slide_list.currentRowChanged.connect(self.show_preview)
        self.preview = QLabel("Open a project to begin")
        self.preview.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.preview.setMinimumSize(480, 320)

        open_button = QPushButton("Open project…")
        open_button.clicked.connect(self.open_project)
        self.export_button = QPushButton("Export…")
        self.export_button.setEnabled(False)
        self.export_button.clicked.connect(self.export_project)

        buttons = QHBoxLayout()
        buttons.addWidget(open_button)
        buttons.addWidget(self.export_button)
        content = QHBoxLayout()
        content.addWidget(self.slide_list, 1)
        content.addWidget(self.preview, 3)
        layout = QVBoxLayout()
        layout.addLayout(buttons)
        layout.addLayout(content)
        container = QWidget()
        container.setLayout(layout)
        self.setCentralWidget(container)

    def open_project(self):
        path, _ = QFileDialog.getOpenFileName(self, "Open project", "", "Slideshow projects (*.slides)")
        if not path:
            return
        try:
            self.project = load_project(path)
        except (OSError, json.JSONDecodeError, ProjectError) as exc:
            QMessageBox.critical(self, "Could not open project", str(exc))
            return
        self.project_file = path
        self.setWindowTitle(f"Slideshow exporter – {self.project['title']}")
        self.slide_list.clear()
        for index, slide in enumerate(self.project["slides"], start=1):
            self.slide_list.addItem(f"{index}. {slide.get('caption') or slide['image']}")
        self.export_button.setEnabled(True)
        self.slide_list.setCurrentRow(0)

    def show_preview(self, row):
        if self.project is None or row < 0:
            return
        project_dir = os.path.dirname(os.path.abspath(self.project_file))
        source = resolve_asset(project_dir, self.project["slides"][row]["image"])
        if Path(source).suffix.lower() not in SUPPORTED_IMAGES:
            self.preview.setText("No preview for this file type")
            return
        pixmap = QPixmap(source)
        if pixmap.isNull():
            self.preview.setText("Image could not be loaded")
            return
        self.preview.setPixmap(pixmap.scaled(self.preview.size(), Qt.AspectRatioMode.KeepAspectRatio))

    def export_project(self):
        output_dir = QFileDialog.getExistingDirectory(self, "Choose export folder")
        if not output_dir:
            return
        try:
            count = export_slideshow(self.project_file, self.project, output_dir)
        except (OSError, ProjectError) as exc:
            QMessageBox.critical(self, "Export failed", str(exc))
            return
        QMessageBox.information(self, "Export complete", f"Exported {count} slide(s) to {output_dir}")


if __name__ == "__main__":
    qt_app = QApplication(sys.argv)
    window = SlideshowWindow()
    window.resize(900, 560)
    window.show()
    sys.exit(qt_app.exec())