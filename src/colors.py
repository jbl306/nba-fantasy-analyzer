"""ANSI color utilities for terminal output.

Provides color helpers for the NBA Fantasy Advisor CLI.  Respects the
``NO_COLOR`` environment variable (https://no-color.org/) and degrades
gracefully when the output stream is not a TTY (e.g. piped to a file).

Color scheme:
  - Green:   Healthy / STRONG / positive signals
  - Yellow:  Day-To-Day (DTD) / Below Avg / caution signals
  - Red:     OUT / OUT-SEASON / WEAK / negative signals
  - Cyan:    Headers and section titles
  - Bold:    Emphasis (player names, key values)
"""

from __future__ import annotations

import os
import sys


# ---------------------------------------------------------------------------
# Detect whether color output is supported
# ---------------------------------------------------------------------------

def _color_enabled() -> bool:
    """Return True if ANSI color output should be used."""
    # Respect the NO_COLOR convention
    if os.environ.get("NO_COLOR"):
        return False
    # If stdout is not a real terminal, skip colors
    if not hasattr(sys.stdout, "isatty") or not sys.stdout.isatty():
        return False
    # On Windows, enable VT processing so ANSI escapes render properly
    if sys.platform == "win32":
        try:
            import ctypes
            kernel32 = ctypes.windll.kernel32  # type: ignore[attr-defined]
            # STD_OUTPUT_HANDLE = -11
            handle = kernel32.GetStdHandle(-11)
            # ENABLE_VIRTUAL_TERMINAL_PROCESSING = 0x0004
            mode = ctypes.c_ulong()
            kernel32.GetConsoleMode(handle, ctypes.byref(mode))
            kernel32.SetConsoleMode(handle, mode.value | 0x0004)
        except Exception:
            pass  # best-effort; some terminals support ANSI natively
    return True


USE_COLOR: bool = _color_enabled()


# ---------------------------------------------------------------------------
# ANSI escape codes
# ---------------------------------------------------------------------------

_RESET = "\033[0m"
_BOLD = "\033[1m"
_DIM = "\033[2m"

_RED = "\033[91m"
_GREEN = "\033[92m"
_YELLOW = "\033[93m"
_CYAN = "\033[96m"
_WHITE = "\033[97m"
_MAGENTA = "\033[95m"


# ---------------------------------------------------------------------------
# Public helpers
# ---------------------------------------------------------------------------

def red(text: str) -> str:
    """Wrap *text* in red (errors, OUT, WEAK)."""
    return f"{_RED}{text}{_RESET}" if USE_COLOR else text


def green(text: str) -> str:
    """Wrap *text* in green (healthy, STRONG)."""
    return f"{_GREEN}{text}{_RESET}" if USE_COLOR else text


def yellow(text: str) -> str:
    """Wrap *text* in yellow (DTD, Below Avg, caution)."""
    return f"{_YELLOW}{text}{_RESET}" if USE_COLOR else text


def cyan(text: str) -> str:
    """Wrap *text* in cyan (headers, titles)."""
    return f"{_CYAN}{text}{_RESET}" if USE_COLOR else text


def bold(text: str) -> str:
    """Wrap *text* in bold."""
    return f"{_BOLD}{text}{_RESET}" if USE_COLOR else text


def dim(text: str) -> str:
    """Wrap *text* in dim/muted style."""
    return f"{_DIM}{text}{_RESET}" if USE_COLOR else text


def magenta(text: str) -> str:
    """Wrap *text* in magenta."""
    return f"{_MAGENTA}{text}{_RESET}" if USE_COLOR else text


# ---------------------------------------------------------------------------
# Semantic colorizers (domain-specific)
# ---------------------------------------------------------------------------

def colorize_injury(status: str) -> str:
    """Colorize an injury status label.

    - ``OUT`` / ``OUT-SEASON`` → red
    - ``DTD`` → yellow
    - ``-`` (healthy) → green
    """
    upper = status.strip().upper()
    if upper in ("OUT", "OUT-SEASON", "INJ", "O", "SUSP"):
        return red(status)
    if upper in ("DTD", "GTD", "DAY-TO-DAY"):
        return yellow(status)
    if upper == "-":
        return green(status)
    return status


def colorize_assessment(assessment: str) -> str:
    """Colorize a team category assessment label.

    - ``STRONG`` → green
    - ``Average`` → white (no color)
    - ``Below Avg`` → yellow
    - ``WEAK`` → red
    """
    upper = assessment.strip().upper()
    if upper == "STRONG":
        return green(assessment)
    if upper == "BELOW AVG":
        return yellow(assessment)
    if upper == "WEAK":
        return red(assessment)
    return assessment  # Average — no color


def colorize_health(flag: str) -> str:
    """Colorize an availability health flag.

    - ``Healthy`` → green
    - ``Moderate`` → yellow
    - ``Risky`` / ``Fragile`` → red
    """
    upper = flag.strip().lower()
    if upper == "healthy":
        return green(flag)
    if upper == "moderate":
        return yellow(flag)
    if upper in ("risky", "fragile"):
        return red(flag)
    return flag


def colorize_budget_status(status: str) -> str:
    """Colorize a FAAB budget status label.

    - ``COMFORTABLE`` / ``FLEXIBLE`` → green
    - ``MODERATE`` → yellow
    - ``CONSERVE`` / ``CRITICAL`` → red
    """
    upper = status.strip().upper()
    if upper in ("COMFORTABLE", "FLEXIBLE"):
        return green(status)
    if upper == "MODERATE":
        return yellow(status)
    if upper in ("CONSERVE", "CRITICAL"):
        return red(status)
    return status


def colorize_tier(tier: str) -> str:
    """Colorize a player quality tier label."""
    upper = tier.strip().lower()
    if upper == "elite":
        return magenta(tier)
    if upper == "strong":
        return green(tier)
    if upper == "solid":
        return cyan(tier)
    if upper == "streamer":
        return yellow(tier)
    if upper == "dart":
        return dim(tier)
    return tier


def colorize_z_score(z: float, formatted: str | None = None) -> str:
    """Colorize a z-score value based on sign.

    - Positive → green
    - Negative → red
    - Near zero (|z| < 0.1) → no color
    """
    text = formatted if formatted is not None else f"{z:+.2f}"
    if z >= 0.1:
        return green(text)
    if z <= -0.1:
        return red(text)
    return text
