"""Theme system — colour tokens and palette/stylesheet generation."""

from __future__ import annotations

from dataclasses import dataclass

from PyQt5.QtGui import QColor, QPalette

_MONO = "'JetBrains Mono', 'Fira Code', Consolas, monospace"


@dataclass(frozen=True)
class Theme:
    """All colour tokens for one display mode."""
    name: str
    # chrome
    bg: str
    panel_bg: str
    border: str
    accent: str
    text: str
    text_dim: str
    # pyqtgraph surfaces
    plot_bg: str
    image_bg: str
    pg_fg: str
    # data curves
    h_curve: str
    v_curve: str
    fit_curve: str

    def palette(self) -> QPalette:
        """Build a QPalette for Fusion style matching this theme's colours."""
        p = QPalette()
        bg      = QColor(self.bg)
        panel   = QColor(self.panel_bg)
        border  = QColor(self.border)
        accent  = QColor(self.accent)
        text    = QColor(self.text)
        dim     = QColor(self.text_dim)

        p.setColor(QPalette.ColorRole.Window,           bg)
        p.setColor(QPalette.ColorRole.WindowText,       text)
        p.setColor(QPalette.ColorRole.Base,             panel)
        p.setColor(QPalette.ColorRole.AlternateBase,    bg)
        p.setColor(QPalette.ColorRole.ToolTipBase,      panel)
        p.setColor(QPalette.ColorRole.ToolTipText,      text)
        p.setColor(QPalette.ColorRole.Text,             text)
        p.setColor(QPalette.ColorRole.Button,           panel)
        p.setColor(QPalette.ColorRole.ButtonText,       text)
        p.setColor(QPalette.ColorRole.BrightText,       QColor("#ffffff"))
        p.setColor(QPalette.ColorRole.Link,             accent)
        p.setColor(QPalette.ColorRole.Highlight,        accent)
        p.setColor(QPalette.ColorRole.HighlightedText,  bg)
        p.setColor(QPalette.ColorRole.Light,            panel.lighter(130))
        p.setColor(QPalette.ColorRole.Midlight,         border)
        p.setColor(QPalette.ColorRole.Mid,              border)
        p.setColor(QPalette.ColorRole.Dark,             bg.darker(130))
        p.setColor(QPalette.ColorRole.Shadow,           bg.darker(160))
        p.setColor(QPalette.ColorRole.PlaceholderText,  dim)
        return p

    def stylesheet(self) -> str:  # noqa: E501
        """Minimal stylesheet that accents Fusion's native widget rendering."""
        return f"""
            QGroupBox {{
                border: 1px solid {self.border};
                border-radius: 6px;
                margin-top: 16px;
                padding: 12px 10px 10px 10px;
                font-weight: 600;
                font-size: 13px;
                color: {self.accent};
            }}
            QGroupBox::title {{
                subcontrol-origin: margin;
                left: 12px;
                padding: 0 6px;
            }}
            QLabel {{ background: transparent; }}
            QSplitter::handle {{
                background: {self.border};
            }}
            QStatusBar {{
                border-top: 1px solid {self.border};
                font-size: 12px;
            }}
            QComboBox:hover, QSpinBox:hover, QDoubleSpinBox:hover {{
                border-color: {self.accent};
            }}
            QComboBox:on {{
                border-color: {self.accent};
            }}
            QComboBox QAbstractItemView {{
                selection-background-color: {self.accent};
                selection-color: {self.bg};
                outline: none;
            }}
            QPushButton {{
                padding: 5px 14px;
                min-height: 26px;
                font-size: 12px;
                font-weight: 600;
            }}
            QPushButton:hover {{
                color: {self.accent};
            }}
            QPushButton:checked {{
                background-color: {self.accent};
                color: {self.bg};
            }}
        """


DARK = Theme(
    name="dark",
    bg="#141423",       panel_bg="#16213e",  border="#1a3a5c",
    accent="#00adb5",   text="#e0e0e0",      text_dim="#7a7a9a",
    plot_bg="#1a1a2e",  image_bg="#000000",  pg_fg="#e0e0e0",
    h_curve="#00e5ff",  v_curve="#ce93d8",   fit_curve="#ff5555",
)

LIGHT = Theme(
    name="light",
    bg="#f0f2f5",       panel_bg="#ffffff",   border="#c8ccd8",
    accent="#0077b6",   text="#1a1a2e",       text_dim="#6b6b85",
    plot_bg="#ffffff",  image_bg="#000000",   pg_fg="#1a1a2e",
    h_curve="#0077b6",  v_curve="#7b2d8b",    fit_curve="#c0392b",
)
