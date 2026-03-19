"""Dialog widgets for the Beam Profile Viewer."""

from __future__ import annotations

from pathlib import Path

from PyQt5.QtCore import Qt
from PyQt5.QtWidgets import (
    QDialog,
    QDialogButtonBox,
    QLabel,
    QListWidget,
    QListWidgetItem,
    QVBoxLayout,
    QWidget,
)


class LoadBackgroundDialog(QDialog):
    """Simple dialog listing saved .npy background files for selection."""

    def __init__(self, files: list, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setWindowTitle("Load Background")
        self.setMinimumSize(400, 300)
        self.selected_path: str | None = None

        lay = QVBoxLayout(self)
        lay.addWidget(QLabel("Select a saved background:"))

        self._list = QListWidget()
        for f in files:
            p = Path(f) if not isinstance(f, Path) else f
            item = QListWidgetItem(p.name)
            item.setData(Qt.UserRole, str(p))
            self._list.addItem(item)
        self._list.itemDoubleClicked.connect(self._accept_item)
        lay.addWidget(self._list)

        btn_box = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        btn_box.accepted.connect(self._accept_selected)
        btn_box.rejected.connect(self.reject)
        lay.addWidget(btn_box)

    def _accept_item(self, item: QListWidgetItem) -> None:
        self.selected_path = item.data(Qt.UserRole)
        self.accept()

    def _accept_selected(self) -> None:
        item = self._list.currentItem()
        if item is not None:
            self.selected_path = item.data(Qt.UserRole)
            self.accept()
