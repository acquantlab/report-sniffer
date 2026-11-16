"""Colour themes shared by the app (web/themes.js holds the same ids) and the exported reports.

The app is a dark terminal; the reports are printed on white, so each theme gives the darker,
print-safe version of its screen colours.
"""
from __future__ import annotations

from reportlab.lib import colors

THEMES = {
    "terminal": {"accent": "#c96a00", "accent2": "#1f5fd0", "accent3": "#14181f", "amber": "#f2a900", "violet": "#5b6472", "prior": "#c9ccd3"},
    "phosphor": {"accent": "#0f8a4b", "accent2": "#0e7f95", "accent3": "#0b3d2a", "amber": "#c9a227", "violet": "#4f6b5c", "prior": "#c5d2ca"},
    "desk": {"accent": "#1c5fb8", "accent2": "#d9730d", "accent3": "#0b2545", "amber": "#e0a100", "violet": "#5b6b82", "prior": "#c3cedd"},
    "paper": {"accent": "#b85c00", "accent2": "#12509e", "accent3": "#14181f", "amber": "#d19a00", "violet": "#666c76", "prior": "#cfcbbf"},
}
DEFAULT = "terminal"


def palette(theme: str) -> dict:
    return THEMES.get(theme) or THEMES[DEFAULT]


def apply(theme: str) -> dict:
    """Point the report and chart colours at the theme; returns the palette (hex strings)."""
    from . import charts, pdfreport
    p = palette(theme)
    c = {k: colors.HexColor(v) for k, v in p.items()}
    charts.PINK, charts.CYAN, charts.BLUE, charts.AMBER, charts.VIOLET, charts.PRIOR = (
        c["accent"], c["accent2"], c["accent3"], c["amber"], c["violet"], c["prior"])
    pdfreport.PINK, pdfreport.CYAN, pdfreport.BLUE = c["accent"], c["accent2"], c["accent3"]
    pdfreport.ACCENT_HEX = p["accent"]
    return p
