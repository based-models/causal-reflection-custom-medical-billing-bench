"""Dry-run prints the gate and does not call a provider."""

from __future__ import annotations

from ncci_bench.cli import main


def test_dry_run_prints_the_thirty_claim_gate(capsys: object) -> None:
    main(["run", "--sessions", "6", "--arms", "glm-baseline,glm-causal", "--dry-run"])
    out = capsys.readouterr().out  # type: ignore[attr-defined]
    assert "sessions 6" in out
    assert "claims 30" in out
    assert "no API calls" in out
    assert out.count(" deleted ") == 2
    assert out.count(" indicator_change ") == 2
    assert out.count(" hard_bundle ") == 2
