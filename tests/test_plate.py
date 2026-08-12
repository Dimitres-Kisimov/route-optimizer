"""The dispatch-board plate system: the shared design contract for Plates 01-04.

These tests pin the parts of the design that are load-bearing: the validated
categorical palette (fixed slots, fixed order — the CVD-safety mechanism), the
never-cycle rule for vehicles beyond slot 8, and the deterministic SVG
scaffolding every plate is built on.
"""

import pytest

from routeopt import plate


def test_vehicle_slots_are_the_validated_palette():
    # The eight fixed slots, in the validated order (dataviz palette validator:
    # adjacent-pair CVD dE >= 8, normal-vision dE >= 15, light surface #fcfcfb).
    # Changing a hex or the order silently would void the validation — pin both.
    assert plate.VEHICLE_SLOTS == (
        "#2a78d6", "#eb6834", "#1baf7a", "#eda100",
        "#e87ba4", "#008300", "#4a3aa7", "#e34948",
    )
    assert plate.BLUE == plate.VEHICLE_SLOTS[0]
    assert plate.ORANGE == plate.VEHICLE_SLOTS[1]
    assert plate.AQUA == plate.VEHICLE_SLOTS[2]


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
