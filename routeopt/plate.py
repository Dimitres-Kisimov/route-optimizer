"""The dispatch-board plate system — one visual language for every deliverable.

Every drawn artifact in ``deliverables/`` is a numbered *plate* on the same
board: the route map is Plate 01 (matplotlib PNG, :mod:`routeopt.report`), and
the hand-drawn SVGs are Plates 02–05 (fleet sensitivity, robustness, fleet
mix, driver shifts). This module holds the shared parts so the plates cannot
drift apart.

**The board is toned to its physical subject: roads and trucks.** Nothing here
is a decorative choice — every tone names a real thing a dispatcher can point
at, and every one of them was put through the data-viz palette validator
before it was written down:

* **Asphalt & concrete neutrals.** The board is kerbside concrete
  (``#faf9f6``); the inks are asphalt — fresh asphalt for titles and key
  figures (``#1d2024``, 15.53:1 on the board), worn asphalt for supporting
  text (``#4c5158``, 7.60:1), weathered concrete for tick labels and captions
  (``#8a8d92``, 3.16:1). Gridlines are chalk hairlines (``#e2e1db``) over a
  kerb-toned baseline (``#c2c0b8``). Text always wears ink, never a series
  colour.
* **Vehicle liveries are the categorical slots.** The eight fixed slots are
  the colours delivery fleets are actually painted — courier blue, haulage
  orange, reefer teal, marking amber, livery rose, haulage green, express
  violet, fleet red — in a fixed order that clears every hard gate on the
  light board: adjacent-pair CVD ΔE **10.9** (protan, target ≥ 8),
  normal-vision ΔE **20.1** (floor ≥ 15), all eight inside the L 0.43–0.77
  band and over the 0.10 chroma floor. Slots are assigned by vehicle number
  and **never cycled**: vehicles 9–16 reuse slots 1–8 with a dashed line — a
  composite colour+dash encoding — and every route also carries a direct
  ``V<n>`` label, so identity is never colour-alone.

  Three slots (reefer teal 2.95:1, marking amber 2.04:1, livery rose 2.67:1)
  sit below 3:1 on the board; the relief is that every plate ships direct
  labels and a CSV/MD table of the same numbers. And the route map is honestly
  an **all-pairs** form — any two routes can end up side by side — where eight
  slots cannot clear the floors (worst all-pairs: fleet red ↔ haulage green
  CVD ΔE 2.5, fleet red ↔ haulage orange normal ΔE 9.4) and no re-ordering
  fixes it. A ten-van map cannot fold vans into "Other", so colour alone is
  *not* claimed to carry identity there: the direct ``V<n>`` labels, the
  per-vehicle legend and ``route_plan.csv`` do, and the palette's job on the
  map is separation between *neighbouring* routes.
* **Painted road markings.** Customer nodes and mark rings are marking white
  (``#ffffff``); the mandated-break blocks on the shift plate are marking
  amber (``#e9a400`` — slot 4 of the same fixed palette, no invented hue).
* **Traffic-signal status, reserved.** ``SIGNAL_RED`` (RAL 3020 traffic red,
  5.55:1) means infeasible / late / over-cap and nothing else; amber, orange
  and green complete the scale. These sit close to their same-hue livery
  neighbours by construction (signal red ↔ fleet red ΔE 4.8, signal amber ↔
  marking amber 4.9 — the same collision the reference palette documents), so
  a signal tone never carries meaning alone: it always ships with a label
  naming the breach.
* **Semantic series roles.** Across plates, blue is the primary cost measure
  (km, EUR), orange the service/risk measure (longest route, failure share,
  time at the kerb), teal the emissions measure, and ``REF_GRAY`` a
  deliberately de-emphasised reference series (a baseline drawn as quiet gray
  under the inked answer — emphasis, not a second rainbow). The gray is
  *meant* to read gray; its separation from blue was still checked (CVD ΔE
  16.1, normal 18.5) and both lines are directly labelled.
* **One axis per panel.** No dual-axis charts: where an old artifact carried
  two y-scales, the plate stacks two panels that share the x axis.
* **Stacked money bars** use a one-hue ordinal blue ramp (light ``#7fb0ee``
  fixed cost under deep ``#1f6fd0`` variable cost — validator ``--ordinal``
  pass, light end 2.13:1), with a 2px surface gap between segments and the
  total labelled.

Determinism: every helper emits plain strings from rounded coordinates — no
timestamps, no randomness — so plate SVGs regenerate byte-identically.
"""

from __future__ import annotations

# --- board surface & ink: asphalt and concrete (the plates are light-only) ---
SURFACE = "#faf9f6"  # the board itself — kerbside concrete
INK = "#1d2024"  # fresh asphalt: titles, key figures (15.53:1)
SECONDARY = "#4c5158"  # worn asphalt: supporting text, direct labels (7.60:1)
MUTED = "#8a8d92"  # weathered concrete: tick labels, eyebrows, captions (3.16:1)
GRID = "#e2e1db"  # chalk hairline gridlines
AXIS = "#c2c0b8"  # kerb line: baseline / axis / frame

# --- validated categorical palette: fixed per-vehicle slots, never cycled ----
# Vehicle liveries — the colours delivery fleets are painted. Light board
# #faf9f6: adjacent CVD ΔE 10.9 (protan), normal-vision ΔE 20.1, band + chroma
# pass. Changing a hex or the order voids that validation.
VEHICLE_SLOTS: tuple[str, ...] = (
    "#1f6fd0",  # 1 courier blue
    "#e8621f",  # 2 haulage orange
    "#12a678",  # 3 reefer teal
    "#e9a400",  # 4 marking amber
    "#e2799f",  # 5 livery rose
    "#00703c",  # 6 haulage green
    "#4d3da4",  # 7 express violet
    "#d33c3a",  # 8 fleet red
)

# The same eight liveries stepped for a dark surface (#1c1f23) — the web map's
# dark mode, validated as its own set: adjacent CVD ΔE 8.2, normal ΔE 17.3,
# L inside 0.48–0.67, every slot >= 3:1 on the dark board.
VEHICLE_SLOTS_DARK: tuple[str, ...] = (
    "#3d85e0",  # 1 courier blue
    "#d95e2a",  # 2 haulage orange
    "#159a6d",  # 3 reefer teal
    "#c08200",  # 4 marking amber
    "#d16b93",  # 5 livery rose
    "#128a4a",  # 6 haulage green
    "#9086e0",  # 7 express violet
    "#e06a68",  # 8 fleet red
)

# semantic series roles shared by every plate
BLUE = VEHICLE_SLOTS[0]  # primary cost measure (distance km, EUR, driving)
ORANGE = VEHICLE_SLOTS[1]  # service / risk measure (incl. time at the kerb)
AQUA = VEHICLE_SLOTS[2]  # emissions measure
BLUE_LIGHT = "#7fb0ee"  # fixed-cost segment of the money stack (ordinal ramp)
MARKING_WHITE = "#ffffff"  # painted road marking: node fills, mark rings
MARKING_AMBER = VEHICLE_SLOTS[3]  # painted road marking: mandated-break blocks
REF_GRAY = "#8a8d92"  # de-emphasised reference series (deliberate gray)
BASELINE_GRAY = "#c6c4bc"  # map underlay for the heuristic baseline routes

# --- traffic-signal status scale (reserved; never a series colour) -----------
# Road signals, not brand hues. Contrast on the light board in brackets; each
# is always paired with a label naming the breach, never colour alone.
SIGNAL_GREEN = "#008351"  # good — RAL 6024 traffic green (4.57:1)
SIGNAL_AMBER = "#f7b500"  # warning — RAL 1023 traffic yellow (1.72:1, label-led)
SIGNAL_ORANGE = "#de5307"  # serious — RAL 2009 traffic orange (3.73:1)
SIGNAL_RED = "#cc0605"  # critical: infeasible / late / over-cap (5.55:1)

FONT = "system-ui,Segoe UI,Arial,sans-serif"
DASH = "6 3.5"  # the shared dash pattern for composite-encoded series


def vehicle_style(v: int) -> tuple[str, bool]:
    """(colour, dashed) for 1-based vehicle ``v`` — fixed slots, never cycled.

    Vehicles 1–8 own slots 1–8 solid; 9–16 reuse the slots dashed (composite
    colour+dash encoding). Beyond 16 the identity burden shifts entirely to the
    direct ``V<n>`` labels and the gray fallback keeps the map honest rather
    than inventing hues.
    """
    if v < 1:
        raise ValueError("vehicle numbers are 1-based")
    if v <= len(VEHICLE_SLOTS):
        return VEHICLE_SLOTS[v - 1], False
    if v <= 2 * len(VEHICLE_SLOTS):
        return VEHICLE_SLOTS[v - 1 - len(VEHICLE_SLOTS)], True
    return REF_GRAY, True


# --- SVG plate scaffolding ---------------------------------------------------

PLATE_W = 760  # shared plate width
MARGIN_L = 56  # room for right-aligned y tick labels
MARGIN_R = 28


def open_svg(w: int, h: int) -> list[str]:
    """The plate canvas: fixed size, board surface, hairline frame."""
    return [
        f'<svg xmlns="http://www.w3.org/2000/svg" width="{w}" height="{h}" '
        f'viewBox="0 0 {w} {h}" font-family="{FONT}">',
        f'<rect width="{w}" height="{h}" fill="{SURFACE}"/>',
        f'<rect x="0.5" y="0.5" width="{w - 1}" height="{h - 1}" fill="none" '
        f'stroke="{GRID}" stroke-width="1"/>',
    ]


def plate_header(out: list[str], plate_no: str, title: str, subtitle: str, x: int = MARGIN_L) -> None:
    """Numbered header: eyebrow, title, honest method subtitle (kept verbatim)."""
    out.append(
        f'<text x="{x}" y="28" font-size="10" font-weight="600" letter-spacing="1.6" '
        f'fill="{MUTED}">PLATE {plate_no} &#183; DISPATCH BOARD</text>'
    )
    out.append(
        f'<text x="{x}" y="52" font-size="17" font-weight="600" fill="{INK}">{title}</text>'
    )
    out.append(f'<text x="{x}" y="70" font-size="11" fill="{SECONDARY}">{subtitle}</text>')


def panel_title(out: list[str], x: float, y: float, text: str) -> None:
    out.append(
        f'<text x="{x}" y="{y}" font-size="11.5" font-weight="600" fill="{INK}">{text}</text>'
    )


def h_grid(
    out: list[str],
    px0: float,
    px1: float,
    py0: float,
    py1: float,
    vmax: float,
    ticks: int = 5,
    fmt: str = "{:.0f}",
) -> None:
    """Hairline horizontal gridlines with muted right-aligned tick labels.

    ``py0`` is the baseline (bottom), ``py1`` the top; the baseline itself is
    drawn in the darker axis tone.
    """
    for i in range(ticks):
        gy = round(py0 + i / (ticks - 1) * (py1 - py0), 2)
        tone, width = (AXIS, 1) if i == 0 else (GRID, 1)
        out.append(
            f'<line x1="{px0}" y1="{gy}" x2="{px1}" y2="{gy}" stroke="{tone}" '
            f'stroke-width="{width}"/>'
        )
        label = fmt.format(vmax * i / (ticks - 1))
        out.append(
            f'<text x="{px0 - 8}" y="{gy + 3.5}" font-size="10" text-anchor="end" '
            f'fill="{MUTED}">{label}</text>'
        )


def x_tick(out: list[str], x: float, py0: float, label: str) -> None:
    out.append(
        f'<line x1="{x}" y1="{py0}" x2="{x}" y2="{py0 + 4}" stroke="{AXIS}" stroke-width="1"/>'
    )
    out.append(
        f'<text x="{x}" y="{py0 + 16}" font-size="10" text-anchor="middle" '
        f'fill="{MUTED}">{label}</text>'
    )


def x_axis_label(out: list[str], px0: float, px1: float, y: float, text: str) -> None:
    out.append(
        f'<text x="{(px0 + px1) / 2}" y="{y}" font-size="11" text-anchor="middle" '
        f'fill="{SECONDARY}">{text}</text>'
    )


def series_line(
    out: list[str],
    points: list[tuple[float, float]],
    color: str,
    width: float = 2,
    dashed: bool = False,
) -> None:
    """A 2px series line with >=8px markers ringed in surface (the 2px ring)."""
    dash = f' stroke-dasharray="{DASH}"' if dashed else ""
    pts = " ".join(f"{x},{y}" for x, y in points)
    out.append(
        f'<polyline points="{pts}" fill="none" stroke="{color}" stroke-width="{width}"{dash}/>'
    )
    for x, y in points:
        out.append(
            f'<circle cx="{x}" cy="{y}" r="4" fill="{color}" stroke="{SURFACE}" stroke-width="2"/>'
        )


def direct_label(
    out: list[str], x: float, y: float, text: str, anchor: str = "start"
) -> None:
    """A direct series label in text ink (never the series colour)."""
    out.append(
        f'<text x="{x}" y="{y}" font-size="10" text-anchor="{anchor}" '
        f'fill="{SECONDARY}">{text}</text>'
    )


def legend_line(
    out: list[str], x: float, y: float, color: str, label: str, dashed: bool = False
) -> None:
    dash = f' stroke-dasharray="{DASH}"' if dashed else ""
    out.append(
        f'<line x1="{x}" y1="{y}" x2="{x + 22}" y2="{y}" stroke="{color}" stroke-width="2"{dash}/>'
    )
    out.append(f'<text x="{x + 28}" y="{y + 3.5}" font-size="10" fill="{SECONDARY}">{label}</text>')


def legend_swatch(out: list[str], x: float, y: float, color: str, label: str) -> None:
    out.append(f'<rect x="{x}" y="{y - 8}" width="12" height="10" fill="{color}"/>')
    out.append(f'<text x="{x + 18}" y="{y + 1}" font-size="10" fill="{SECONDARY}">{label}</text>')


def stacked_bar(
    out: list[str],
    x_center: float,
    bar_w: float,
    py0: float,
    y_split: float,
    y_top: float,
    lower_color: str = BLUE_LIGHT,
    upper_color: str = BLUE,
) -> None:
    """A two-segment stacked bar: lower segment anchored to the baseline,
    upper segment separated by a 2px surface gap, 3px-rounded data end on top.
    """
    x0 = round(x_center - bar_w / 2, 2)
    x1 = round(x_center + bar_w / 2, 2)
    if py0 - y_split > 0.5:
        out.append(
            f'<rect x="{x0}" y="{y_split}" width="{round(bar_w, 2)}" '
            f'height="{round(py0 - y_split, 2)}" fill="{lower_color}"/>'
        )
    seg_top = round(y_split - 2, 2)  # the 2px surface gap between segments
    if seg_top - y_top > 0.5:
        r = 3
        out.append(
            f'<path d="M {x0} {seg_top} L {x0} {round(y_top + r, 2)} '
            f'Q {x0} {y_top} {round(x0 + r, 2)} {y_top} '
            f'L {round(x1 - r, 2)} {y_top} Q {x1} {y_top} {x1} {round(y_top + r, 2)} '
            f'L {x1} {seg_top} Z" fill="{upper_color}"/>'
        )


def bar(
    out: list[str], x_center: float, bar_w: float, py0: float, y_top: float, color: str
) -> None:
    """A single thin bar, baseline-anchored, 3px-rounded data end."""
    x0 = round(x_center - bar_w / 2, 2)
    x1 = round(x_center + bar_w / 2, 2)
    if py0 - y_top > 0.5:
        r = min(3, round((py0 - y_top) / 2, 2))
        out.append(
            f'<path d="M {x0} {py0} L {x0} {round(y_top + r, 2)} '
            f'Q {x0} {y_top} {round(x0 + r, 2)} {y_top} '
            f'L {round(x1 - r, 2)} {y_top} Q {x1} {y_top} {x1} {round(y_top + r, 2)} '
            f'L {x1} {py0} Z" fill="{color}"/>'
        )


def x_grid(
    out: list[str],
    px0: float,
    px1: float,
    py0: float,
    py1: float,
    vmax: float,
    ticks: int = 6,
    fmt: str = "{:.0f}",
    labels: bool = True,
) -> None:
    """Vertical hairline gridlines with muted tick labels under the baseline.

    The mirror of :func:`h_grid` for panels whose *shared* quantity runs along
    x (the shift plate's minutes-of-the-day axis). ``py0`` is the baseline
    (bottom), ``py1`` the top; the left edge wears the darker axis tone. Set
    ``labels=False`` for the upper of two panels that share one x scale.
    """
    for i in range(ticks):
        gx = round(px0 + i / (ticks - 1) * (px1 - px0), 2)
        tone = AXIS if i == 0 else GRID
        out.append(
            f'<line x1="{gx}" y1="{py0}" x2="{gx}" y2="{py1}" stroke="{tone}" stroke-width="1"/>'
        )
        if labels:
            out.append(
                f'<text x="{gx}" y="{py0 + 14}" font-size="10" text-anchor="middle" '
                f'fill="{MUTED}">{fmt.format(vmax * i / (ticks - 1))}</text>'
            )


def h_bar_segments(
    out: list[str],
    px0: float,
    y_top: float,
    height: float,
    segments: list[tuple[float, str]],
) -> float:
    """A horizontal bar built from ``(width_px, colour)`` segments, left-anchored.

    Segments are separated by the shared 2px surface gap and the last one gets
    the 3px rounded data end, exactly as the vertical bars do. Returns the x of
    the bar's end so the caller can hang a direct label off it.
    """
    x = px0
    drawn = [(w, c) for w, c in segments if w > 0.5]
    for k, (seg_w, colour) in enumerate(drawn):
        last = k == len(drawn) - 1
        w = round(seg_w - (0 if last else 2), 2)  # the 2px surface gap
        if w <= 0.5:
            x = round(x + seg_w, 2)
            continue
        x0, y0 = round(x, 2), round(y_top, 2)
        y1 = round(y_top + height, 2)
        if last:
            r = min(3.0, round(w / 2, 2))
            x1 = round(x0 + w, 2)
            out.append(
                f'<path d="M {x0} {y0} L {round(x1 - r, 2)} {y0} Q {x1} {y0} {x1} '
                f'{round(y0 + r, 2)} L {x1} {round(y1 - r, 2)} Q {x1} {y1} '
                f'{round(x1 - r, 2)} {y1} L {x0} {y1} Z" fill="{colour}"/>'
            )
        else:
            out.append(
                f'<rect x="{x0}" y="{y0}" width="{w}" height="{round(height, 2)}" fill="{colour}"/>'
            )
        x = round(x + seg_w, 2)
    return round(x, 2)


def rule_v(
    out: list[str],
    x: float,
    y0: float,
    y1: float,
    colour: str,
    label: str,
    dashed: bool = True,
    anchor: str = "start",
    label_y: float | None = None,
) -> None:
    """A vertical threshold rule with its own label — a limit, not a series.

    Used for the driver-shift cap in ``SIGNAL_RED``: the status colour never
    stands alone, the label naming the limit rides with it. Anchor the label
    ``end`` when the rule sits near the right edge so the text turns inward
    instead of running off the plate.
    """
    dash = f' stroke-dasharray="{DASH}"' if dashed else ""
    out.append(
        f'<line x1="{x}" y1="{y0}" x2="{x}" y2="{y1}" stroke="{colour}" '
        f'stroke-width="1.5"{dash}/>'
    )
    off = -5 if anchor == "end" else 5
    ly = round(y0 - 5 if label_y is None else label_y, 2)
    out.append(
        f'<text x="{round(x + off, 2)}" y="{ly}" font-size="9.5" text-anchor="{anchor}" '
        f'font-weight="600" fill="{colour}">{label}</text>'
    )


def footer(out: list[str], w: int, h: int, text: str) -> None:
    """The honest plate footer, muted, above the bottom frame line."""
    out.append(
        f'<text x="{MARGIN_L}" y="{h - 14}" font-size="9.5" fill="{MUTED}">{text}</text>'
    )


def close_svg(out: list[str]) -> None:
    out.append("</svg>")
