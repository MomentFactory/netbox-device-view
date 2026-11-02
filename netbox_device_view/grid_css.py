"""
Parse and generate the ``grid-template-areas`` CSS stored on a DeviceView.

This module is the single source of truth for converting between the CSS text
saved in ``DeviceView.grid_template_area`` and the structured layout used by
the visual builder.  It has no Django dependencies so it can be unit tested on
its own.

A layout config (``DeviceView.layout_config``, version 2) looks like::

    {
        "version": 2,
        "mode": "builder",
        "source_device_type_id": 12,
        "layouts": [
            {
                "selector": ".deviceview.area",
                "label": "C9300-24T",
                "rows": 2,
                "columns": 32,
                "grid": [["gigabitethernet0-1", ".", ...], [...]],
                "declarations": "grid-auto-rows: auto",
            },
            ...
        ],
        "extra_css": "",
    }

Each layout becomes one CSS rule block.  Blocks the builder cannot represent
(no ``grid-template-areas``, unusual selectors, at-rules) are kept verbatim in
``extra_css`` so nothing is lost on a round trip.
"""

import re

EMPTY_TOKEN = "."
# Legacy builder marker for an intentional gap; rendered the same as an empty cell.
SPACE_TOKEN = "__space__"
# Filler names used by hand-written layouts (see README): leading "x", trailing
# "z", in-between "s0".."s99", and "y" seen in several examples.
FILLER_PATTERN = re.compile(r"^(\.+|x|y|z|s\d+|__space__)$")
AREA_PATTERN = re.compile(r"^-?[a-zA-Z_][a-zA-Z0-9_-]*$")
SELECTOR_PATTERN = re.compile(r"^\.deviceview(\.[A-Za-z_][\w-]*)*$")
BASE_SELECTOR = ".deviceview.area"
FORBIDDEN_DECLARATION_CHARS = set("{}<>")
ROW_STRING_PATTERN = re.compile(r"\"([^\"]*)\"|'([^']*)'")
COMMENT_PATTERN = re.compile(r"/\*.*?\*/", re.DOTALL)
# The CSS is printed raw inside <style>: "<" could close the tag, "\" escapes
# could hide the keywords below, and these keywords load or run external code.
FORBIDDEN_CSS_CHARS = ("<", "\\")
FORBIDDEN_CSS_PATTERN = re.compile(
    r"@import|url\s*\(|expression\s*\(|javascript\s*:|behavior\s*:|-moz-binding|image-set\s*\(|src\s*\(",
    re.IGNORECASE,
)


def css_problems(css):
    """Return a list of reasons *css* is unsafe to embed in a page (empty when safe)."""
    text = str(css or "")
    problems = [f"CSS may not contain '{char}'." for char in FORBIDDEN_CSS_CHARS if char in text]
    for keyword in sorted({match.group(0).lower() for match in FORBIDDEN_CSS_PATTERN.finditer(text)}):
        problems.append(f"CSS may not contain '{keyword}'.")
    return problems


def is_filler(token):
    return not token or bool(FILLER_PATTERN.match(token))


def _normalize_token(token):
    token = str(token or "").strip()
    return EMPTY_TOKEN if is_filler(token) else token


def _normalize_grid(grid):
    rows = [[_normalize_token(token) for token in row] for row in (grid or []) if isinstance(row, (list, tuple))]
    rows = [row for row in rows if row]
    columns = max((len(row) for row in rows), default=0)
    return [row + [EMPTY_TOKEN] * (columns - len(row)) for row in rows]


def _make_layout(selector, label, grid, declarations):
    grid = _normalize_grid(grid)
    return {
        "selector": " ".join(str(selector or BASE_SELECTOR).split()),
        "label": " ".join(str(label or "").split()),
        "rows": len(grid),
        "columns": len(grid[0]) if grid else 0,
        "grid": grid,
        "declarations": str(declarations or "").strip(),
    }


def _find_block_end(text, start):
    """Return the index of the ``}`` matching the ``{`` at *start*, skipping comments."""
    depth = 0
    i = start
    while i < len(text):
        if text.startswith("/*", i):
            end = text.find("*/", i + 2)
            i = len(text) if end == -1 else end + 2
            continue
        if text[i] == "{":
            depth += 1
        elif text[i] == "}":
            depth -= 1
            if depth == 0:
                return i
        i += 1
    return len(text)


def _parse_body(body):
    """Split a rule body into (grid rows or None, other declarations)."""
    body = COMMENT_PATTERN.sub("", body)
    grid = None
    declarations = []
    # A missing ";" before "}" simply leaves the last declaration unterminated.
    for declaration in body.split(";"):
        prop, sep, value = declaration.partition(":")
        if not sep:
            continue
        prop = prop.strip()
        if prop.lower() == "grid-template-areas":
            grid = [(match.group(1) if match.group(1) is not None else match.group(2)).split() for match in ROW_STRING_PATTERN.finditer(value)]
        else:
            declarations.append(f"{prop}: {' '.join(value.split())}")
    return grid, declarations


def parse_grid_css(css):
    """
    Parse DeviceView CSS into ``{"layouts": [...], "extra_css": str}``.

    Tolerant of the formats found in the wild: several rule blocks (module or
    front/rear variants), extra declarations, a missing final semicolon, legacy
    filler names and ports spanning several cells.
    """
    text = str(css or "")
    layouts = []
    extra_blocks = []
    pending_comment = ""
    buffer_start = 0
    i = 0

    while i < len(text):
        if text.startswith("/*", i):
            end = text.find("*/", i + 2)
            end = len(text) if end == -1 else end
            if not text[buffer_start:i].strip():
                # A comment between blocks labels the next block.
                pending_comment = text[i + 2 : end].strip()
                buffer_start = end + 2
            i = end + 2
            continue
        if text[i] == "{":
            selector = COMMENT_PATTERN.sub("", text[buffer_start:i]).strip()
            close = _find_block_end(text, i)
            body = text[i + 1 : close]
            grid, declarations = _parse_body(body) if "{" not in body else (None, [])

            if grid and SELECTOR_PATTERN.match(" ".join(selector.split())):
                layouts.append(_make_layout(selector, pending_comment, grid, "\n".join(declarations)))
            elif selector or body.strip():
                block = f"{selector} {{{body}}}".strip()
                if pending_comment:
                    block = f"/* {_safe_comment(pending_comment)} */\n{block}"
                extra_blocks.append(block)

            pending_comment = ""
            i = close + 1
            buffer_start = i
            continue
        i += 1

    return {"layouts": layouts, "extra_css": "\n\n".join(extra_blocks)}


def _safe_comment(text):
    return " ".join(str(text or "").replace("*/", "* /").replace("<", " ").replace("\\", " ").split())


def normalize_config(config):
    """
    Return a version-2 builder config, upgrading the version-1 single-grid
    format.  Returns ``None`` when *config* is not a builder config.
    """
    if not isinstance(config, dict) or config.get("mode") != "builder":
        return None

    if isinstance(config.get("layouts"), list):
        layouts = [
            _make_layout(
                layout.get("selector"),
                layout.get("label"),
                layout.get("grid"),
                layout.get("declarations"),
            )
            for layout in config["layouts"]
            if isinstance(layout, dict)
        ]
    else:
        layouts = [_make_layout(BASE_SELECTOR, "", config.get("grid"), "")]

    return {
        "version": 2,
        "mode": "builder",
        "source_device_type_id": config.get("source_device_type_id"),
        "layouts": layouts,
        "extra_css": str(config.get("extra_css") or "").strip(),
    }


def validate_layout(layout):
    """Return a list of human-readable problems with *layout* (empty when valid)."""
    errors = []
    name = layout.get("label") or layout.get("selector") or "layout"

    if not SELECTOR_PATTERN.match(layout.get("selector", "")):
        errors.append(f"{name}: selector must look like '.deviceview.area' or '.deviceview.moduleX.area'.")

    declarations = layout.get("declarations", "")
    if FORBIDDEN_DECLARATION_CHARS & set(declarations):
        errors.append(f"{name}: extra declarations may not contain {{ }} < or >.")
    errors.extend(f"{name}: {problem}" for problem in css_problems(declarations) if "'<'" not in problem)
    if "grid-template-areas" in declarations.lower():
        errors.append(f"{name}: put grid-template-areas in the grid, not in extra declarations.")

    grid = layout.get("grid") or []
    if not grid:
        errors.append(f"{name}: the grid is empty.")
        return errors

    for token, problem in area_problems(grid).items():
        errors.append(f"{name}: '{token}' {problem}")
    return errors


def area_problems(grid):
    """Return ``{token: problem}`` for areas the browser would reject."""
    problems = {}
    cells = {}
    for r, row in enumerate(grid):
        for c, token in enumerate(row):
            if token == EMPTY_TOKEN:
                continue
            if not AREA_PATTERN.match(token):
                problems[token] = f"at R{r + 1}C{c + 1} is not a valid area name."
                continue
            cells.setdefault(token, []).append((r, c))

    for token, positions in cells.items():
        rows = [r for r, _ in positions]
        cols = [c for _, c in positions]
        if len(positions) != (max(rows) - min(rows) + 1) * (max(cols) - min(cols) + 1):
            cells_text = ", ".join(f"R{r + 1}C{c + 1}" for r, c in positions)
            problems[token] = f"must fill a rectangle ({cells_text})."
    return problems


def generate_layout_css(layout, selector=None):
    lines = []
    if layout.get("label") and selector is None:
        lines.append(f"/* {_safe_comment(layout['label'])} */")
    lines.append(f"{selector or layout['selector']} {{")
    for declaration in layout.get("declarations", "").splitlines():
        declaration = declaration.strip().rstrip(";").strip()
        if declaration:
            lines.append(f"    {declaration};")
    rows = ['        "' + " ".join(row) + '"' for row in layout["grid"]]
    lines.append("    grid-template-areas:")
    lines.append("\n".join(rows) + ";")
    lines.append("}")
    return "\n".join(lines)


def generate_grid_css(config):
    """
    Convert a builder config into DeviceView CSS.  Raises ``ValueError`` listing
    every problem when the config is invalid.  Returns "" for non-builder configs.
    """
    config = normalize_config(config)
    if config is None:
        return ""
    if not config["layouts"]:
        raise ValueError("Add at least one layout.")

    errors = [error for layout in config["layouts"] for error in validate_layout(layout)]
    if errors:
        raise ValueError(" ".join(errors))

    blocks = [generate_layout_css(layout) for layout in config["layouts"]]
    if config["extra_css"]:
        problems = css_problems(config["extra_css"])
        if problems:
            raise ValueError("Extra CSS: " + " ".join(problems))
        blocks.append(config["extra_css"])
    return "\n\n".join(blocks)


def describe_grid_css(css):
    """Short summary for tables, e.g. '2 × 32 · 2 variants'."""
    parsed = parse_grid_css(css)
    layouts = parsed["layouts"]
    if not layouts:
        return "custom CSS" if str(css or "").strip() else "empty"
    first = layouts[0]
    summary = f"{first['rows']} × {first['columns']}"
    if len(layouts) > 1:
        summary += f" · {len(layouts)} variants"
    return summary
