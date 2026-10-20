"""Matplotlib chart generation with robust edge-case handling and theme styling."""

from typing import Dict, Optional, Tuple
import matplotlib
import matplotlib.pyplot as plt
from matplotlib.figure import Figure
import numpy as np
import pandas as pd

# Use non-interactive backend for embedded generation
matplotlib.use("Agg")
from matplotlib.backends.backend_qtagg import FigureCanvasQTAgg
from PySide6.QtCore import Qt
from PySide6.QtWidgets import QSizePolicy, QWidget

from desktop_intelligence.ui.theme import get_effective_theme

BASE_DPI = 100.0


def get_chart_theme_colors(theme_mode: str = "light", accent_color: Optional[str] = None) -> Dict[str, str]:
    """Return styling color tokens for charts based on theme mode and accent."""
    effective = get_effective_theme(theme_mode)
    is_dark = (effective == "dark")
    default_accent = "#8B5CF6" if is_dark else "#6957E8"
    accent = accent_color or default_accent

    if is_dark:
        return {
            "fig_bg": "#0E1422",
            "plot_bg": "#0E1422",
            "text": "#F3F5FC",
            "secondary_text": "#A7B2C8",
            "grid": "#1F293D",
            "border": "#25314C",
            "accent": accent,
            "cyan": "#22D3EE",
            "idle": "#FBBF24",
            "cmap": "Purples" if any(k in accent.lower() for k in ["8b5c", "635b", "7c3a"]) else "Blues",
        }
    else:
        return {
            "fig_bg": "#FFFFFF",
            "plot_bg": "#FFFFFF",
            "text": "#182033",
            "secondary_text": "#55627A",
            "grid": "#EAF0FA",
            "border": "#E2E8F0",
            "accent": accent,
            "cyan": "#0891B2",
            "idle": "#D97706",
            "cmap": "Purples" if any(k in accent.lower() for k in ["8b5c", "635b", "7c3a"]) else "Blues",
        }


def create_empty_figure(
    message: str = "No activity data recorded yet.",
    theme_mode: str = "light",
    accent_color: Optional[str] = None,
) -> Figure:
    """Return an empty figure with a user-friendly notice and proper theme colors."""
    colors = get_chart_theme_colors(theme_mode, accent_color)
    fig = Figure(figsize=(6, 3), dpi=BASE_DPI, facecolor=colors["fig_bg"], layout="constrained")
    ax = fig.add_subplot(111, facecolor=colors["plot_bg"])
    ax.text(0.5, 0.5, message, ha="center", va="center", color=colors["secondary_text"], fontsize=10)
    ax.set_xticks([])
    ax.set_yticks([])
    ax.spines[:].set_visible(False)
    return fig


def create_top_apps_chart(
    summary_df: pd.DataFrame,
    top_n: int = 7,
    theme_mode: str = "light",
    accent_color: Optional[str] = None,
) -> Figure:
    """Horizontal bar chart showing active hours of top applications."""
    colors = get_chart_theme_colors(theme_mode, accent_color)

    if summary_df is None or summary_df.empty or "process_name" not in summary_df.columns:
        return create_empty_figure("No application usage recorded.", theme_mode, accent_color)

    # Sanitize and extract top apps
    clean_df = summary_df.dropna(subset=["process_name"]).copy()
    if clean_df.empty:
        return create_empty_figure("No application usage recorded.", theme_mode, accent_color)

    clean_df["active_hours"] = pd.to_numeric(clean_df.get("active_hours", 0.0), errors="coerce").fillna(0.0)
    top_df = clean_df.head(top_n).iloc[::-1]

    apps = top_df["process_name"].astype(str).tolist()
    hours = top_df["active_hours"].astype(float).tolist()

    if not apps:
        return create_empty_figure("No application usage recorded.", theme_mode, accent_color)

    fig = Figure(figsize=(6, 3.2), dpi=BASE_DPI, facecolor=colors["fig_bg"], layout="constrained")
    ax = fig.add_subplot(111, facecolor=colors["plot_bg"])

    y_pos = np.arange(len(apps))
    bars = ax.barh(y_pos, hours, color=colors["accent"], edgecolor="none", height=0.6)

    ax.set_yticks(y_pos)
    ax.set_yticklabels(apps, fontsize=9, color=colors["text"])
    ax.set_xlabel("Active Hours", fontsize=9, color=colors["secondary_text"])
    ax.set_title(f"Top {len(apps)} Applications by Usage Time", fontsize=10, weight="bold", pad=8, color=colors["text"])

    ax.grid(axis="x", linestyle="--", alpha=0.4, color=colors["grid"])
    ax.spines["top"].set_visible(False)
    ax.spines["right"].set_visible(False)
    ax.spines["left"].set_color(colors["border"])
    ax.spines["bottom"].set_color(colors["border"])
    ax.tick_params(colors=colors["secondary_text"], which="both")

    # Safe x-axis limit: avoid identical low and high xlim when max_h is 0
    max_h = float(np.nanmax(hours)) if len(hours) > 0 and not np.isnan(np.nanmax(hours)) else 0.0
    if max_h <= 0.0:
        upper_limit = 1.0
    else:
        upper_limit = max_h * 1.15

    ax.set_xlim(0, upper_limit)

    # Annotate bar values
    for bar in bars:
        w = bar.get_width()
        val_text = f"{w:.1f}h" if w > 0 else "0h"
        offset = max(upper_limit * 0.02, 0.02)
        ax.text(
            w + offset,
            bar.get_y() + bar.get_height() / 2,
            val_text,
            va="center",
            fontsize=8,
            color=colors["secondary_text"],
        )

    return fig


def create_daily_trend_chart(
    daily_df: pd.DataFrame,
    theme_mode: str = "light",
    accent_color: Optional[str] = None,
) -> Figure:
    """Line / area chart showing daily active vs idle usage over time."""
    colors = get_chart_theme_colors(theme_mode, accent_color)

    if daily_df is None or daily_df.empty or "local_date" not in daily_df.columns:
        return create_empty_figure("No daily history recorded.", theme_mode, accent_color)

    clean_df = daily_df.dropna(subset=["local_date"]).copy()
    if clean_df.empty:
        return create_empty_figure("No daily history recorded.", theme_mode, accent_color)

    dates = clean_df["local_date"].astype(str).tolist()
    active = pd.to_numeric(clean_df.get("active_hours", 0.0), errors="coerce").fillna(0.0).tolist()
    idle = pd.to_numeric(clean_df.get("idle_hours", 0.0), errors="coerce").fillna(0.0).tolist()

    fig = Figure(figsize=(6, 3.2), dpi=BASE_DPI, facecolor=colors["fig_bg"], layout="constrained")
    ax = fig.add_subplot(111, facecolor=colors["plot_bg"])

    x = np.arange(len(dates))
    ax.plot(x, active, color=colors["accent"], marker="o", markersize=4, label="Active Time", linewidth=2)
    ax.plot(x, idle, color=colors["idle"], marker="s", markersize=4, label="Idle Time", linewidth=1.5, linestyle="--")

    ax.set_xticks(x)
    step = max(1, len(dates) // 6)
    labels = [d if i % step == 0 else "" for i, d in enumerate(dates)]
    ax.set_xticklabels(labels, rotation=25, ha="right", fontsize=8, color=colors["secondary_text"])
    ax.set_ylabel("Hours", fontsize=9, color=colors["secondary_text"])
    ax.set_title("Daily Usage Trend", fontsize=10, weight="bold", pad=8, color=colors["text"])

    ax.legend(loc="upper left", frameon=False, fontsize=8, labelcolor=colors["text"])
    ax.grid(True, linestyle="--", alpha=0.4, color=colors["grid"])
    ax.spines["top"].set_visible(False)
    ax.spines["right"].set_visible(False)
    ax.spines["left"].set_color(colors["border"])
    ax.spines["bottom"].set_color(colors["border"])
    ax.tick_params(colors=colors["secondary_text"], which="both")

    # Safe y-axis limit
    all_vals = active + idle
    max_val = float(np.nanmax(all_vals)) if all_vals and not np.isnan(np.nanmax(all_vals)) else 0.0
    if max_val <= 0.0:
        ax.set_ylim(0, 1.0)
    else:
        ax.set_ylim(0, max_val * 1.2)

    return fig


def create_day_of_week_chart(
    dow_df: pd.DataFrame,
    theme_mode: str = "light",
    accent_color: Optional[str] = None,
) -> Figure:
    """Bar chart showing active hours across days of the week."""
    colors = get_chart_theme_colors(theme_mode, accent_color)

    if dow_df is None or dow_df.empty or "day_of_week" not in dow_df.columns:
        return create_empty_figure("No day-of-week data available.", theme_mode, accent_color)

    days = [str(d)[:3] for d in dow_df["day_of_week"].tolist()]
    hours = pd.to_numeric(dow_df.get("active_hours", 0.0), errors="coerce").fillna(0.0).tolist()

    fig = Figure(figsize=(5, 3), dpi=BASE_DPI, facecolor=colors["fig_bg"], layout="constrained")
    ax = fig.add_subplot(111, facecolor=colors["plot_bg"])

    x = np.arange(len(days))
    ax.bar(x, hours, color=colors["accent"], width=0.55)

    ax.set_xticks(x)
    ax.set_xticklabels(days, fontsize=9, color=colors["text"])
    ax.set_ylabel("Active Hours", fontsize=9, color=colors["secondary_text"])
    ax.set_title("Weekly Distribution", fontsize=10, weight="bold", pad=8, color=colors["text"])

    ax.grid(axis="y", linestyle="--", alpha=0.4, color=colors["grid"])
    ax.spines["top"].set_visible(False)
    ax.spines["right"].set_visible(False)
    ax.spines["left"].set_color(colors["border"])
    ax.spines["bottom"].set_color(colors["border"])
    ax.tick_params(colors=colors["secondary_text"], which="both")

    max_h = float(np.nanmax(hours)) if hours and not np.isnan(np.nanmax(hours)) else 0.0
    if max_h <= 0.0:
        ax.set_ylim(0, 1.0)
    else:
        ax.set_ylim(0, max_h * 1.15)

    return fig


def create_hourly_heatmap_chart(
    matrix: np.ndarray,
    theme_mode: str = "light",
    accent_color: Optional[str] = None,
) -> Figure:
    """7x24 heatmap matrix showing usage density by day of week and hour of day."""
    colors = get_chart_theme_colors(theme_mode, accent_color)

    if matrix is None or matrix.shape != (7, 24) or np.all(np.isnan(matrix)) or np.nanmax(matrix) == 0:
        return create_empty_figure("No hourly pattern data available yet.", theme_mode, accent_color)

    # Replace NaNs or Infs with 0
    clean_mat = np.nan_to_num(matrix, nan=0.0, posinf=0.0, neginf=0.0)

    days = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"]
    hours = [f"{h:02d}" for h in range(24)]

    fig = Figure(figsize=(7, 2.8), dpi=BASE_DPI, facecolor=colors["fig_bg"], layout="constrained")
    ax = fig.add_subplot(111, facecolor=colors["plot_bg"])

    im = ax.imshow(clean_mat, cmap=colors["cmap"], aspect="auto", interpolation="nearest")

    ax.set_yticks(np.arange(len(days)))
    ax.set_yticklabels(days, fontsize=8, color=colors["text"])

    ax.set_xticks(np.arange(0, 24, 2))
    ax.set_xticklabels([hours[i] for i in range(0, 24, 2)], fontsize=8, color=colors["secondary_text"])

    ax.set_xlabel("Hour of Day (Local)", fontsize=8, color=colors["secondary_text"])
    ax.set_title("Activity Heatmap (Active Minutes)", fontsize=10, weight="bold", pad=8, color=colors["text"])

    cbar = fig.colorbar(im, ax=ax, fraction=0.03, pad=0.04)
    cbar.ax.tick_params(labelsize=7, colors=colors["secondary_text"])

    ax.tick_params(colors=colors["secondary_text"], which="both")
    ax.spines[:].set_color(colors["border"])

    return fig


class ThemedChartCanvas(FigureCanvasQTAgg):
    """Matplotlib canvas that fills its widget at any Windows display scale."""

    def __init__(self, fig: Optional[Figure] = None, parent: Optional[QWidget] = None):
        super().__init__(fig if fig is not None else create_empty_figure())
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        self._applied_dpr = None
        # Matplotlib sets WA_OpaquePaintEvent; unless it is turned off the canvas paints white.
        self.setAttribute(Qt.WA_OpaquePaintEvent, False)
        self.setAutoFillBackground(False)
        self.setStyleSheet("background: transparent;")
        self._style_surface(self.figure)
        self._sync_dimensions()

    @staticmethod
    def _style_surface(fig: Figure) -> None:
        fig.patch.set_alpha(0.0)
        for ax in fig.axes:
            ax.patch.set_alpha(0.0)

    def _sync_dimensions(self) -> None:
        fig = self.figure
        if fig is None:
            return
        dpr = float(self.device_pixel_ratio)
        fig.set_dpi(BASE_DPI * dpr)  # physical pixels per inch
        fig.set_size_inches(max(self.width(), 1) / BASE_DPI, max(self.height(), 1) / BASE_DPI, forward=False)
        self._applied_dpr = dpr

    def update_chart_figure(self, fig: Figure) -> None:
        old = self.figure
        self.figure = fig
        fig.set_canvas(self)
        self._style_surface(fig)
        self._sync_dimensions()
        self.draw()
        if old is not None and old is not fig:
            old.clear()  # release artists promptly

    update_figure = update_chart_figure

    def showEvent(self, event) -> None:
        super().showEvent(event)
        if self._applied_dpr != self.device_pixel_ratio:
            self._sync_dimensions()
            self.draw_idle()

    # No resizeEvent override: FigureCanvasQT.resizeEvent already multiplies by device_pixel_ratio.

