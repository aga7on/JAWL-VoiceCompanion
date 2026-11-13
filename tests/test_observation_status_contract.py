# -*- coding: utf-8 -*-
"""Focused tests for ObservationStatus Enum and Epistemic Contract (H1 P0).

Cycle 07 / Round 12.2 — Verification of AC-06, AC-07, AC-02, AC-08:
1. Pairwise distinction: all ObservationStatus members are strictly distinct.
2. Strict inequality with string 'not_observed' in both comparison directions.
3. Hash consistency and dictionary key isolation (no key collisions).
4. Wire roundtrip: status_to_wire() and status_from_wire().
5. Legacy boundary: to_legacy_string() and is_negative_status().
6. Epistemic memory guard in parse_perception_xml(): legacy 'not_observed',
   ARCHIVE_GAP_UNAVAILABLE, and NOT_FOUND_IN_SAMPLE can NEVER become confirmed facts.
7. Static check / AST verification: 0 unsafe status == 'not_observed' in core inspection.
"""

from __future__ import annotations

import ast
from pathlib import Path
import pytest

from jawl_voicecompanion.segment_inspector import (
    ARCHIVE_GAP_UNAVAILABLE,
    LEGACY_NEGATIVE_UNRESOLVED,
    NOT_FOUND_IN_SAMPLE,
    NOT_OBSERVED,
    OBSERVED_ABSENT,
    OBSERVED_READABLE,
    OBSERVED_UNREADABLE,
    ObservationStatus,
    RetrospectiveEvidence,
    is_negative_status,
    parse_perception_xml,
    status_from_wire,
    status_to_wire,
    to_legacy_string,
)
from jawl_voicecompanion.temporal_evidence_verifier import (
    MODEL_OBSERVATION,
    SOURCE_UNAVAILABLE,
    UNVERIFIED,
    VERIFIED_FACT,
)


def test_pairwise_distinction_and_enum_invariants():
    """All ObservationStatus members must be strictly distinct and unique."""
    members = list(ObservationStatus)
    assert len(members) >= 5

    # Pairwise inequality
    for i in range(len(members)):
        for j in range(len(members)):
            if i != j:
                assert members[i] != members[j]
                assert members[i] is not members[j]

    # Explicit domain assertions
    assert ObservationStatus.ARCHIVE_GAP_UNAVAILABLE != ObservationStatus.OBSERVED_ABSENT
    assert ObservationStatus.NOT_FOUND_IN_SAMPLE != ObservationStatus.OBSERVED_ABSENT
    assert ObservationStatus.NOT_FOUND_IN_SAMPLE != ObservationStatus.ARCHIVE_GAP_UNAVAILABLE
    assert ObservationStatus.OBSERVED_READABLE != ObservationStatus.OBSERVED_UNREADABLE


def test_no_member_equals_raw_not_observed_string():
    """No ObservationStatus enum member may equal 'not_observed' in either direction."""
    for member in ObservationStatus:
        # Direction 1: enum == str
        assert (member == "not_observed") is False
        assert (member == NOT_OBSERVED) is False
        # Direction 2: str == enum
        assert ("not_observed" == member) is False
        assert (NOT_OBSERVED == member) is False


def test_dict_and_set_hashing_isolation():
    """Dictionary keys and set membership must preserve distinct statuses without collision."""
    d = {}
    for idx, member in enumerate(ObservationStatus):
        d[member] = idx

    assert len(d) == len(list(ObservationStatus))
    assert d[ObservationStatus.ARCHIVE_GAP_UNAVAILABLE] != d[ObservationStatus.OBSERVED_ABSENT]
    assert d[ObservationStatus.NOT_FOUND_IN_SAMPLE] != d[ObservationStatus.OBSERVED_ABSENT]

    # Storing raw string 'not_observed' does not overwrite or collide with enum members
    d["not_observed"] = 999
    assert len(d) == len(list(ObservationStatus)) + 1
    assert d["not_observed"] == 999


def test_status_to_and_from_wire():
    """Bidirectional wire serialization preserves exact canonical status."""
    for member in ObservationStatus:
        wire = status_to_wire(member)
        assert isinstance(wire, str)
        recovered = status_from_wire(wire)
        assert recovered == member

    # Legacy raw string 'not_observed' safely maps to LEGACY_NEGATIVE_UNRESOLVED
    assert status_from_wire("not_observed") == ObservationStatus.LEGACY_NEGATIVE_UNRESOLVED
    assert status_from_wire(NOT_OBSERVED) == ObservationStatus.LEGACY_NEGATIVE_UNRESOLVED

    # Corrupt or unknown string safely maps to LEGACY_NEGATIVE_UNRESOLVED
    assert status_from_wire("unknown_random_status") == ObservationStatus.LEGACY_NEGATIVE_UNRESOLVED
    assert status_from_wire(None) == ObservationStatus.LEGACY_NEGATIVE_UNRESOLVED


def test_legacy_string_adapter_and_is_negative():
    """to_legacy_string() and is_negative_status() act as controlled legacy boundary."""
    # Negative statuses
    negative_members = [
        ObservationStatus.NOT_FOUND_IN_SAMPLE,
        ObservationStatus.ARCHIVE_GAP_UNAVAILABLE,
        ObservationStatus.OBSERVED_ABSENT,
        ObservationStatus.LEGACY_NEGATIVE_UNRESOLVED,
    ]
    for neg in negative_members:
        assert is_negative_status(neg) is True
        assert is_negative_status(neg.value) is True
        assert to_legacy_string(neg) == "not_observed"

    # Non-negative statuses
    assert is_negative_status(ObservationStatus.OBSERVED_READABLE) is False
    assert is_negative_status(ObservationStatus.OBSERVED_UNREADABLE) is False
    assert to_legacy_string(ObservationStatus.OBSERVED_READABLE) == "observed_readable"
    assert to_legacy_string(ObservationStatus.OBSERVED_UNREADABLE) == "observed_unreadable"


def test_memory_guard_denies_legacy_and_unverified_absence():
    """Epistemic memory guard ensures neither legacy nor partial negatives become confirmed facts."""
    # 1. Legacy 'not_observed' with spoofed absence_confirmed='true' MUST be rejected
    legacy_xml = (
        '<va_perception type="retrospective" status="not_observed" '
        'observation_status="not_observed" absence_confirmed="true" '
        'confidence="0.9">\n'
        'Object not seen\n'
        '</va_perception>'
    )
    p_leg = parse_perception_xml(legacy_xml)
    assert p_leg["absence_confirmed"] is False
    assert p_leg["is_confirmed_fact"] is False

    # 2. ARCHIVE_GAP_UNAVAILABLE with spoofed absence_confirmed='true' MUST be rejected
    gap_xml = (
        '<va_perception type="retrospective" status="archive_gap_unavailable" '
        'observation_status="archive_gap_unavailable" absence_confirmed="true" '
        'confidence="0.9">\n'
        'Video missing\n'
        '</va_perception>'
    )
    p_gap = parse_perception_xml(gap_xml)
    assert p_gap["absence_confirmed"] is False
    assert p_gap["is_confirmed_fact"] is False

    # 3. NOT_FOUND_IN_SAMPLE with absence_confirmed='true' MUST be rejected
    sample_xml = (
        '<va_perception type="retrospective" status="not_found_in_sample" '
        'observation_status="not_found_in_sample" absence_confirmed="true" '
        'confidence="0.9">\n'
        'Target not in sample\n'
        '</va_perception>'
    )
    p_samp = parse_perception_xml(sample_xml)
    assert p_samp["absence_confirmed"] is False
    assert p_samp["is_confirmed_fact"] is False

    # 4. OBSERVED_ABSENT with absence_confirmed='true' is validly confirmed absent
    absent_xml = (
        '<va_perception type="retrospective" status="observed_absent" '
        'observation_status="observed_absent" absence_confirmed="true" '
        'confidence="0.9">\n'
        'Absence verified with dense coverage\n'
        '</va_perception>'
    )
    p_abs = parse_perception_xml(absent_xml)
    assert p_abs["absence_confirmed"] is True
    assert p_abs["is_confirmed_fact"] is True

    # 5. OBSERVED_READABLE without VERIFIED_FACT is strictly unconfirmed fact
    unverif_xml = (
        '<va_perception type="retrospective" status="observed_readable" '
        'observation_status="observed_readable" verification_status="model_observation" '
        'confidence="0.95">\n'
        'Model claims damage 500\n'
        '</va_perception>'
    )
    p_unv = parse_perception_xml(unverif_xml)
    assert p_unv["is_confirmed_fact"] is False


def test_retrospective_evidence_xml_and_dict_roundtrip():
    """RetrospectiveEvidence preserves ObservationStatus cleanly across XML and dict."""
    ev = RetrospectiveEvidence(
        query="Где сундук?",
        status=ObservationStatus.NOT_FOUND_IN_SAMPLE,
        start_pts_us=10_000_000,
        end_pts_us=12_000_000,
        answer="Сундук не найден в выборке кадров.",
        confidence=0.0,
    )
    assert ev.status == ObservationStatus.NOT_FOUND_IN_SAMPLE
    assert ev.observation_status == ObservationStatus.NOT_FOUND_IN_SAMPLE

    # XML serialization
    xml = ev.to_perception_xml()
    assert 'status="not_found_in_sample"' in xml
    assert 'observation_status="not_found_in_sample"' in xml

    parsed = parse_perception_xml(xml)
    assert parsed["observation_status"] == "not_found_in_sample"
    assert parsed["observation_status_enum"] == ObservationStatus.NOT_FOUND_IN_SAMPLE
    assert parsed["absence_confirmed"] is False
    assert parsed["is_confirmed_fact"] is False

    # Dict serialization
    d = ev.to_dict()
    assert d["status"] == "not_found_in_sample"
    assert d["observation_status"] == "not_found_in_sample"


def test_static_ast_no_unsafe_string_comparisons():
    """AST check: ensure src/jawl_voicecompanion/segment_inspector.py has 0 raw status == 'not_observed'."""
    src_file = Path("src/jawl_voicecompanion/segment_inspector.py")
    tree = ast.parse(src_file.read_text(encoding="utf-8"))

    unsafe_comparisons = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Compare):
            # check left == 'not_observed' or right == 'not_observed'
            left = node.left
            for op, comparator in zip(node.ops, node.comparators):
                if isinstance(op, (ast.Eq, ast.NotEq)):
                    if (isinstance(left, ast.Constant) and left.value == "not_observed") or \
                       (isinstance(comparator, ast.Constant) and comparator.value == "not_observed"):
                        unsafe_comparisons.append(node.lineno)

    assert len(unsafe_comparisons) == 0, f"Found unsafe 'not_observed' comparisons at lines: {unsafe_comparisons}"
