"""Theme and glassmorphism styling system for Desktop Intelligence.

Provides refined glassmorphic design tokens, layered translucent surfaces,
side-glow accent treatment, Windows system theme detection, and cohesive
Qt stylesheets for Light and Dark modes.
"""

import sys
from typing import Dict, Optional

ACCENT_PRESETS: Dict[str, str] = {
    "Indigo (Default)": "#635BFF",
    "Electric Violet": "#8B5CF6",
    "Cyan Glow": "#22D3EE",
    "Emerald": "#34D399",
    "Royal Blue": "#2563EB",
    "Amber Glow": "#FBBF24",
    "Rose": "#FB7185",
}

DEFAULT_DARK_ACCENT = "#8B5CF6"
DEFAULT_LIGHT_ACCENT = "#635BFF"


def get_contrast_text_color(hex_color: str) -> str:
    """Return '#FFFFFF' or '#0F172A' depending on luminance of hex_color for accessible WCAG AA contrast."""
    hex_clean = hex_color.lstrip("#")
    if len(hex_clean) == 6:
        try:
            r = int(hex_clean[0:2], 16) / 255.0
            g = int(hex_clean[2:4], 16) / 255.0
            b = int(hex_clean[4:6], 16) / 255.0
            lum = 0.2126 * r + 0.7152 * g + 0.0722 * b
            return "#0F172A" if lum > 0.55 else "#FFFFFF"
        except Exception:
            pass
    return "#FFFFFF"


def is_system_dark_mode() -> bool:
    """Detect if Windows OS has dark mode enabled for applications."""
    if sys.platform != "win32":
        return False
    try:
        import winreg
        key = winreg.OpenKey(
            winreg.HKEY_CURRENT_USER,
            r"Software\Microsoft\Windows\CurrentVersion\Themes\Personalize",
        )
        val, _ = winreg.QueryValueEx(key, "AppsUseLightTheme")
        winreg.CloseKey(key)
        return val == 0
    except Exception:
        return False


def get_effective_theme(theme_setting: str) -> str:
    """Resolve 'system' to either 'light' or 'dark' based on OS preferences."""
    mode = str(theme_setting).lower().strip()
    if mode == "system":
        return "dark" if is_system_dark_mode() else "light"
    return "dark" if mode == "dark" else "light"


def get_theme_palette(theme_mode: str = "light", accent_color: Optional[str] = None) -> Dict[str, str]:
    """Return dictionary of design tokens for the specified theme and accent."""
    effective = get_effective_theme(theme_mode)

    if effective == "dark":
        accent = accent_color or DEFAULT_DARK_ACCENT
        return {
            "mode": "dark",
            "app_bg": "#0A0D16",
            "depth_bg": "#0E1422",
            "surface_bg": "rgba(24, 31, 48, 0.72)",
            "surface_solid": "#141A29",
            "surface_elevated": "rgba(31, 40, 61, 0.82)",
            "surface_alt": "#1A2234",
            "glass_border": "rgba(180, 198, 240, 0.14)",
            "border": "#212A3D",
            "border_subtle": "rgba(180, 198, 240, 0.08)",
            "text_primary": "#F3F5FC",
            "text_secondary": "#A7B2C8",
            "text_muted": "#7F8BA5",
            "sidebar_bg": "#0C1220",
            "sidebar_border": "rgba(139, 92, 246, 0.22)",
            "sidebar_hover": "rgba(139, 92, 246, 0.12)",
            "sidebar_selected_bg": "qlineargradient(x1:0, y1:0, x2:1, y2:0, stop:0 rgba(139, 92, 246, 0.28), stop:1 rgba(34, 211, 238, 0.08))",
            "sidebar_text": "#A7B2C8",
            "sidebar_text_selected": "#FFFFFF",
            "accent": accent,
            "accent_text": get_contrast_text_color(accent),
            "accent_glow": "rgba(139, 92, 246, 0.35)",
            "accent_hover": "#9D74FF",
            "cyan": "#22D3EE",
            "input_bg": "#0E1422",
            "input_border": "rgba(180, 198, 240, 0.18)",
            "table_header_bg": "#121826",
            "table_alt_bg": "rgba(18, 24, 38, 0.50)",
            "success": "#34D399",
            "warning": "#FBBF24",
            "error": "#FB7185",
        }
    else:
        accent = accent_color or DEFAULT_LIGHT_ACCENT
        return {
            "mode": "light",
            "app_bg": "#F3F6FC",
            "depth_bg": "#EAF0FA",
            "surface_bg": "rgba(255, 255, 255, 0.78)",
            "surface_solid": "#FFFFFF",
            "surface_elevated": "#FFFFFF",
            "surface_alt": "#F1F5FB",
            "glass_border": "rgba(73, 89, 125, 0.16)",
            "border": "#E2E8F0",
            "border_subtle": "rgba(73, 89, 125, 0.08)",
            "text_primary": "#182033",
            "text_secondary": "#55627A",
            "text_muted": "#68758B",
            "sidebar_bg": "#0F172A",
            "sidebar_border": "rgba(105, 87, 232, 0.22)",
            "sidebar_hover": "rgba(255, 255, 255, 0.06)",
            "sidebar_selected_bg": "qlineargradient(x1:0, y1:0, x2:1, y2:0, stop:0 rgba(105, 87, 232, 0.32), stop:1 rgba(8, 145, 178, 0.10))",
            "sidebar_text": "#94A3B8",
            "sidebar_text_selected": "#FFFFFF",
            "accent": accent,
            "accent_text": get_contrast_text_color(accent),
            "accent_glow": "rgba(105, 87, 232, 0.25)",
            "accent_hover": "#5B48DB",
            "cyan": "#0891B2",
            "input_bg": "#FFFFFF",
            "input_border": "#CBD5E1",
            "table_header_bg": "#F8FAFC",
            "table_alt_bg": "rgba(241, 245, 251, 0.60)",
            "success": "#059669",
            "warning": "#D97706",
            "error": "#DC2626",
        }


def generate_stylesheet(theme_mode: str = "light", accent_color: Optional[str] = None) -> str:
    """Generate a full Qt stylesheet implementing elegant glassmorphism and side glow."""
    p = get_theme_palette(theme_mode, accent_color)

    return f"""
    /* Global Window & Fonts */
    QMainWindow {{
        background-color: {p["app_bg"]};
        font-family: 'Segoe UI';
    }}
    QWidget#centralWidget {{
        background-color: {p["app_bg"]};
    }}
    QScrollArea {{
        background-color: transparent;
        border: none;
    }}
    QScrollArea#rec_scroll, QWidget#rec_container {{
        background-color: transparent;
        border: none;
    }}

    /* Sidebar Navigation with Translucent Surface & Side Glow Border */
    QWidget#sidebar_container {{
        background-color: {p["sidebar_bg"]};
        border-right: 1px solid {p["sidebar_border"]};
    }}
    QListWidget#nav_list {{
        background-color: transparent;
        color: {p["sidebar_text"]};
        border: none;
        font-size: 13px;
        font-weight: 500;
        outline: none;
        padding-top: 8px;
    }}
    QListWidget#nav_list::item {{
        padding: 12px 18px;
        border-left: 3px solid transparent;
        margin: 3px 10px;
        border-radius: 8px;
    }}
    QListWidget#nav_list::item:hover {{
        background-color: {p["sidebar_hover"]};
        color: {p["sidebar_text_selected"]};
    }}
    QListWidget#nav_list::item:selected {{
        background: {p["sidebar_selected_bg"]};
        color: {p["sidebar_text_selected"]};
        border-left: 3px solid {p["accent"]};
        font-weight: 600;
    }}

    /* Stacked Widget & Content Pages */
    QStackedWidget {{
        background-color: {p["app_bg"]};
    }}
    QWidget {{
        color: {p["text_primary"]};
        font-size: 12px;
    }}

    /* Typography Classes */
    QLabel#page_title {{
        color: {p["text_primary"]};
        font-size: 20px;
        font-weight: bold;
    }}
    QLabel#section_title {{
        color: {p["text_primary"]};
        font-size: 14px;
        font-weight: 600;
        margin-top: 6px;
    }}
    QLabel#subtitle, QLabel#caption {{
        color: {p["text_secondary"]};
        font-size: 11px;
    }}
    QLabel#badge {{
        background-color: {p["surface_alt"]};
        color: {p["accent"]};
        border: 1px solid {p["glass_border"]};
        border-radius: 4px;
        padding: 2px 6px;
        font-size: 11px;
        font-weight: 600;
    }}

    /* Glass Cards & Panels with Thin Translucent Borders */
    QFrame#glass_card, MetricCard, QFrame#chart_card {{
        background-color: {p["surface_bg"]};
        border: 1px solid {p["glass_border"]};
        border-radius: 12px;
    }}
    QFrame#glass_card_elevated {{
        background-color: {p["surface_elevated"]};
        border: 1px solid {p["glass_border"]};
        border-radius: 12px;
    }}

    /* Metric Summary Cards */
    MetricCard {{
        background-color: {p["surface_bg"]};
        border: 1px solid {p["glass_border"]};
        border-radius: 12px;
    }}
    MetricCard QLabel#title {{
        color: {p["text_secondary"]};
        font-size: 11px;
        font-weight: 600;
        letter-spacing: 0.5px;
    }}
    MetricCard QLabel#value {{
        color: {p["text_primary"]};
        font-size: 22px;
        font-weight: bold;
    }}

    /* Recommendation Cards */
    RecommendationWidget {{
        background-color: {p["surface_bg"]};
        border: 1px solid {p["glass_border"]};
        border-radius: 12px;
    }}

    /* Data Tables with Coherent Glass Styling & Full Width */
    QTableWidget {{
        background-color: {p["surface_bg"]};
        border: 1px solid {p["glass_border"]};
        border-radius: 8px;
        gridline-color: {p["border_subtle"]};
        color: {p["text_primary"]};
        selection-background-color: {p["surface_alt"]};
        selection-color: {p["text_primary"]};
        alternate-background-color: {p["table_alt_bg"]};
    }}
    QTableWidget::item {{
        padding: 7px 12px;
        border-bottom: 1px solid {p["border_subtle"]};
    }}
    QTableWidget::item:selected {{
        background-color: {p["surface_alt"]};
        color: {p["text_primary"]};
    }}
    QHeaderView::section {{
        background-color: {p["table_header_bg"]};
        color: {p["text_secondary"]};
        font-weight: 600;
        font-size: 11px;
        padding: 9px 12px;
        border: none;
        border-bottom: 1px solid {p["glass_border"]};
    }}

    /* Form Inputs */
    QLineEdit, QComboBox, QSpinBox, QDoubleSpinBox {{
        background-color: {p["input_bg"]};
        color: {p["text_primary"]};
        border: 1px solid {p["input_border"]};
        border-radius: 6px;
        padding: 7px 12px;
        font-size: 12px;
    }}
    QLineEdit:focus, QComboBox:focus, QSpinBox:focus, QDoubleSpinBox:focus {{
        border: 1px solid {p["accent"]};
    }}
    QComboBox::drop-down {{
        border: none;
        padding-right: 10px;
    }}
    QComboBox QAbstractItemView {{
        background-color: {p["surface_solid"]};
        color: {p["text_primary"]};
        border: 1px solid {p["glass_border"]};
        selection-background-color: {p["surface_alt"]};
        selection-color: {p["text_primary"]};
        border-radius: 6px;
        padding: 4px;
    }}

    /* Buttons with Soft Accent Elevation */
    QPushButton {{
        background-color: {p["surface_alt"]};
        color: {p["text_primary"]};
        border: 1px solid {p["glass_border"]};
        border-radius: 6px;
        padding: 7px 16px;
        font-weight: 600;
        font-size: 12px;
    }}
    QPushButton:hover {{
        background-color: {p["border"]};
    }}
    QPushButton#primary_btn {{
        background-color: {p["accent"]};
        color: {p["accent_text"]};
        border: 1px solid {p["accent"]};
        border-radius: 6px;
        padding: 6px 14px;
        font-weight: 600;
    }}
    QPushButton#primary_btn:hover {{
        background-color: {p["accent_hover"]};
    }}
    QPushButton#danger_btn {{
        background-color: transparent;
        color: {p["error"]};
        border: 1px solid {p["glass_border"]};
        border-radius: 6px;
        padding: 6px 14px;
        font-weight: 600;
    }}
    QPushButton#danger_btn:hover {{
        background-color: rgba(251, 113, 133, 0.12);
        border: 1px solid {p["error"]};
    }}

    /* Checkboxes */
    QCheckBox {{
        color: {p["text_primary"]};
        spacing: 8px;
        font-size: 12px;
    }}
    QCheckBox::indicator {{
        width: 16px;
        height: 16px;
        border: 1px solid {p["input_border"]};
        border-radius: 4px;
        background-color: {p["input_bg"]};
    }}
    QCheckBox::indicator:checked {{
        background-color: {p["accent"]};
        border-color: {p["accent"]};
    }}

    /* Scrollbars */
    QScrollBar:vertical {{
        background-color: transparent;
        width: 8px;
        margin: 0px;
    }}
    QScrollBar::handle:vertical {{
        background-color: {p["glass_border"]};
        min-height: 24px;
        border-radius: 4px;
    }}
    QScrollBar::handle:vertical:hover {{
        background-color: {p["text_muted"]};
    }}
    QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {{
        height: 0px;
    }}
    QScrollBar:horizontal {{
        background-color: transparent;
        height: 8px;
        margin: 0px;
    }}
    QScrollBar::handle:horizontal {{
        background-color: {p["glass_border"]};
        min-width: 24px;
        border-radius: 4px;
    }}
    QScrollBar::handle:horizontal:hover {{
        background-color: {p["text_muted"]};
    }}
    QScrollBar::add-line:horizontal, QScrollBar::sub-line:horizontal {{
        width: 0px;
    }}
    """
