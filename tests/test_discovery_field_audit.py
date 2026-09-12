"""Regress independently audited source field facts on synthetic byte records."""

from __future__ import annotations

import json

import pytest
from discovery_helpers import FIXTURES, master

from phalanx.discovery.policy import evaluate
from phalanx.domain.discovery import Market
from phalanx.kis.master_parsing import parse_master

_AUDIT = json.loads((FIXTURES / "field_audit.json").read_text())
_SAMPLES = [
    (market, sample) for market, audit in _AUDIT["markets"].items() for sample in audit["samples"]
]


@pytest.mark.parametrize(
    ("market_name", "sample"),
    _SAMPLES,
    ids=[f"{market}-{sample['kind']}" for market, sample in _SAMPLES],
)
@pytest.mark.parametrize("ending", [b"", b"\n", b"\r\n"])
def test_audited_absolute_positions_raw_and_normalized_values(
    market_name: str, sample: dict[str, object], ending: bytes
) -> None:
    market = Market(market_name)
    audit = _AUDIT["markets"][market_name]
    # Fill irrelevant fields with synthetic data. Use only audited facts at independent offsets.
    patches = {
        offset: sample["raw"][field].encode("ascii")
        for field, (offset, width) in audit["offsets"].items()
    }
    patches[0] = sample["short_code"].encode("ascii").ljust(9)
    patches[21] = sample["name"].encode("cp949").ljust(40)
    row = master(market, patches)
    assert len(row) == 61 + audit["suffix_bytes"] == sample["byte_length"]
    assert len(row.decode("cp949")) == sample["character_length"]
    # The suffix boundary computed from the end agrees with the independently fixed byte 61.
    assert row[-audit["suffix_bytes"] :] == row[61:]
    parsed = parse_master(market, row + ending)
    assert parsed.issues == ()
    record = parsed.records[0]
    assert record.short_code == sample["short_code"]
    for field, expected in sample["raw"].items():
        assert record.raw_fields[field] == expected
    for field, expected in sample["normalized"].items():
        assert getattr(record, field) == expected
    decision = evaluate(record)
    assert decision.status == sample["expected_v2_status"]
    assert {r.code for r in decision.reasons} == set(sample["expected_v2_codes"])
