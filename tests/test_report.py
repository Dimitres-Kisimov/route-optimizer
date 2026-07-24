from routeopt.report import build_deliverables


def test_build_deliverables_writes_files(tiny, tmp_path):
    out = build_deliverables(tiny, time_limit_s=2, out_dir=tmp_path)
    for key in ("csv", "png", "summary"):
        assert out[key].exists(), f"{key} not written"
    assert (tmp_path / "route_plan.csv").read_text().startswith("vehicle,")
    assert "summary" in (tmp_path / "summary.md").read_text().lower()
    # all three methods present and feasible on the tiny instance
    assert out["or_tools"].feasible
    assert out["clarke_wright"].feasible
    assert out["nearest_neighbour"].feasible
