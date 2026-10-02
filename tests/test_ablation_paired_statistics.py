from __future__ import annotations

import math

import pytest

from multicat.ablation.paired_statistics import (
    exact_mcnemar,
    holm_adjust,
    wilson_interval,
)


def test_wilson_interval_matches_known_12_of_50_result():
    low, high = wilson_interval(12, 50)
    assert low == pytest.approx(0.142974, abs=1e-6)
    assert high == pytest.approx(0.374127, abs=1e-6)


def test_exact_mcnemar_uses_only_discordant_pairs():
    result = exact_mcnemar(full_errors=[False] * 12, comparator_errors=[True] * 12)
    assert result.full_clean_comparator_error == 12
    assert result.full_error_comparator_clean == 0
    assert result.p_value == pytest.approx(0.00048828125)


def test_holm_adjust_is_monotonic_and_bounded():
    adjusted = holm_adjust([0.01, 0.04, 0.20])
    assert adjusted == pytest.approx([0.03, 0.08, 0.20])
    assert all(0 <= value <= 1 for value in adjusted)


def test_paired_statistics_rejects_unequal_lengths():
    with pytest.raises(ValueError, match="equal length"):
        exact_mcnemar([True], [True, False])
