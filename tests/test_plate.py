"""The dispatch-board plate system: the shared design contract for Plates 01-05.

These tests pin the parts of the design that are load-bearing: the validated
vehicle-livery palette (fixed slots, fixed order — the CVD-safety mechanism),
the never-cycle rule for vehicles beyond slot 8, the reserved traffic-signal
status scale, and the deterministic SVG scaffolding every plate is built on.
"""

import pytest

from routeopt import plate


def test_vehicle_slots_are_the_validated_livery_palette():
    # The eight fixed livery slots, in the validated order (dataviz palette
    # validator on the concrete board #faf9f6: adjacent-pair CVD dE 10.9,
    # normal-vision dE 20.1, all inside the L 0.43-0.77 band, chroma >= 0.10).
    # Changing a hex or the order silently would void the validation — pin both.
    assert plate.VEHICLE_SLOTS == (
        "#1f6fd0", "#e8621f", "#12a678", "#e9a400",
        "#e2799f", "#00703c", "#4d3da4", "#d33c3a",
    )
    # the dark steps for the web map: same eight hues, stepped for #1c1f23
    assert plate.VEHICLE_SLOTS_DARK == (
        "#3d85e0", "#d95e2a", "#159a6d", "#c08200",
        "#d16b93", "#128a4a", "#9086e0", "#e06a68",
    )
    assert len(plate.VEHICLE_SLOTS) == len(plate.VEHICLE_SLOTS_DARK) == 8
    assert plate.BLUE == plate.VEHICLE_SLOTS[0]
    assert plate.ORANGE == plate.VEHICLE_SLOTS[1]
    assert plate.AQUA == plate.VEHICLE_SLOTS[2]
    # road markings are painted, not invented: the break block reuses slot 4
    assert plate.MARKING_AMBER == plate.VEHICLE_SLOTS[3]
    assert plate.MARKING_WHITE == "#ffffff"


def test_traffic_signal_status_is_reserved_and_never_a_series():
    # Status wears road signals and is deliberately kept out of the series
    # palette, so a status colour can never impersonate a vehicle.
    status = (plate.SIGNAL_GREEN, plate.SIGNAL_AMBER, plate.SIGNAL_ORANGE, plate.SIGNAL_RED)
    assert plate.SIGNAL_RED == "#cc0605"  # RAL 3020 traffic red: over-cap / late
    assert len(set(status)) == 4
    assert not set(status) & set(plate.VEHICLE_SLOTS)
    assert not set(status) & set(plate.VEHICLE_SLOTS_DARK)


def test_board_neutrals_are_asphalt_and_concrete():
    # The surface/ink tones the whole board is built on. Pinned because every
    # contrast figure in the module docstring is measured against them.
    assert plate.SURFACE == "#faf9f6"  # kerbside concrete
    assert plate.INK == "#1d2024"  # fresh asphalt
    assert plate.SECONDARY == "#4c5158"
    assert plate.MUTED == "#8a8d92"


def test_vehicle_style_fixed_slots_never_cycled():
    # 1-8: own slot, solid. 9-16: same slots again but DASHED (composite
    # colour+dash encoding — never a generated ninth hue). 17+: honest gray.
    for v in range(1, 9):
        assert plate.vehicle_style(v) == (plate.VEHICLE_SLOTS[v - 1], False)
    for v in range(9, 17):
        assert plate.vehicle_style(v) == (plate.VEHICLE_SLOTS[v - 9], True)
    assert plate.vehicle_style(17) == (plate.REF_GRAY, True)
    with pytest.raises(ValueError):
        plate.vehicle_style(0)


def test_svg_scaffolding_is_deterministic_and_well_formed():
    def build() -> str:
        out = plate.open_svg(760, 640)
        plate.plate_header(out, "09", "A title", "an honest subtitle")
        plate.h_grid(out, 56, 732, 306, 130, 100.0)
        plate.series_line(out, [(56.0, 306.0), (732.0, 130.0)], plate.BLUE)
        plate.footer(out, 760, 640, "footer")
        plate.close_svg(out)
        return "\n".join(out)

    a, b = build(), build()
    assert a == b, "plate helpers must be byte-deterministic"
    assert a.startswith("<svg")
    assert a.endswith("</svg>")
    assert "PLATE 09" in a
    assert plate.SURFACE in a  # the board surface is painted, not transparent


def test_h_grid_draws_requested_ticks():
    out: list[str] = []
    plate.h_grid(out, 56, 732, 306, 130, 500.0, ticks=6)
    lines = [s for s in out if s.startswith("<line")]
    labels = [s for s in out if s.startswith("<text")]
    assert len(lines) == 6
    assert len(labels) == 6
    assert ">500<" in labels[-1] and ">0<" in labels[0]


def test_x_grid_mirrors_h_grid_and_can_drop_its_labels():
    # The shared-x helper: gridlines always, labels only where the axis is read
    # (the upper of two panels sharing one scale passes labels=False).
    out: list[str] = []
    plate.x_grid(out, 56, 732, 306, 130, 600.0, ticks=6)
    assert len([s for s in out if s.startswith("<line")]) == 6
    labels = [s for s in out if s.startswith("<text")]
    assert len(labels) == 6 and ">600<" in labels[-1] and ">0<" in labels[0]

    quiet: list[str] = []
    plate.x_grid(quiet, 56, 732, 306, 130, 600.0, ticks=6, labels=False)
    assert len([s for s in quiet if s.startswith("<line")]) == 6
    assert not [s for s in quiet if s.startswith("<text")]


def test_h_bar_segments_gaps_and_end():
    # A three-segment horizontal bar: every segment but the last is inset by
    # the shared 2px surface gap, and the returned x is the true bar end.
    out: list[str] = []
    end = plate.h_bar_segments(out, 56.0, 100.0, 12.0, [(40.0, plate.BLUE), (30.0, plate.ORANGE), (20.0, plate.MARKING_AMBER)])
    assert end == 146.0  # 56 + 40 + 30 + 20
    assert 'width="38.0"' in out[0] and 'width="28.0"' in out[1]  # 2px gaps
    assert out[-1].startswith("<path")  # the last segment gets the rounded end
    # zero-width segments are dropped rather than drawn as slivers
    thin: list[str] = []
    plate.h_bar_segments(thin, 0.0, 0.0, 10.0, [(0.0, plate.BLUE), (25.0, plate.ORANGE)])
    assert len(thin) == 1


def test_rule_v_always_carries_its_label():
    # A status colour never stands alone: the threshold rule ships the label
    # naming the limit, and turns inward when asked to.
    out: list[str] = []
    plate.rule_v(out, 700.0, 100.0, 300.0, plate.SIGNAL_RED, "10 h duty cap", anchor="end")
    assert len(out) == 2
    assert plate.SIGNAL_RED in out[0] and "stroke-dasharray" in out[0]
    assert 'text-anchor="end"' in out[1] and "10 h duty cap" in out[1]
