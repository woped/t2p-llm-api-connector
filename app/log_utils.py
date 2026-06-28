"""Shared ANSI helpers for emphasising key values inside log messages.

The pretty console formatter (see the entrypoint) colours each line's timestamp,
level and logger name. These helpers let individual messages additionally
highlight a few important values — token totals and cost — so they stand out at a
glance during a live/dev run.

Colour is a single global toggle, set from the formatter selection. When it is
off (e.g. JSON logs, or a non-TTY) every helper returns its text unchanged, so
structured output never gets polluted with escape codes.
"""

RESET = "\033[0m"
BOLD = "\033[1m"
GREEN = "\033[32m"
YELLOW = "\033[33m"
CYAN = "\033[36m"

_color_enabled = False


def set_color_enabled(enabled):
    """Enable or disable colour for all message highlighting."""
    global _color_enabled
    _color_enabled = bool(enabled)


def emphasize(text, *codes):
    """Wrap ``text`` in the given ANSI codes when colour is on, else return it
    unchanged."""
    if not _color_enabled or not codes:
        return str(text)
    return f"{''.join(codes)}{text}{RESET}"


def format_cost(actual, full, cached, compare=False):
    """Build the ``cost=…`` fragment for a usage log line.

    ``actual`` is the real cost (cached tokens billed at the reduced rate);
    ``full`` is the hypothetical cost with no caching. When ``compare`` is set and
    caching actually saved something (``cached`` > 0 and ``full`` > ``actual``) a
    no-cache comparison is appended so the saving is obvious — used only on the
    per-request total line, not on individual calls. Returns ``""`` when no cost
    is known.
    """
    if actual is None:
        return ""
    money = emphasize(f"${actual:.6f}", BOLD, YELLOW)
    if compare and cached and full is not None and full > actual:
        saved = full - actual
        pct = saved / full * 100 if full else 0
        saved_str = emphasize(f"${saved:.6f}", BOLD, GREEN)
        return f"cost={money} (no cache: ${full:.6f}, saved {saved_str} / {pct:.1f}%)"
    return f"cost={money}"
