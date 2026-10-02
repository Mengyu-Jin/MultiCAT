from __future__ import annotations

import math
from dataclasses import dataclass


def wilson_interval(successes: int, total: int, z: float = 1.959963984540054) -> tuple[float, float]:
    if total <= 0 or not 0 <= successes <= total:
        raise ValueError("successes and total must satisfy 0 <= successes <= total and total > 0")
    proportion = successes / total
    denominator = 1 + z * z / total
    center = (proportion + z * z / (2 * total)) / denominator
    half_width = z * math.sqrt(
        proportion * (1 - proportion) / total + z * z / (4 * total * total)
    ) / denominator
    return center - half_width, center + half_width


@dataclass(frozen=True)
class McNemarResult:
    full_clean_comparator_error: int
    full_error_comparator_clean: int
    discordant_pairs: int
    p_value: float


def exact_mcnemar(full_errors: list[bool], comparator_errors: list[bool]) -> McNemarResult:
    if len(full_errors) != len(comparator_errors):
        raise ValueError("Paired inputs must have equal length.")
    b = sum((not full) and comparator for full, comparator in zip(full_errors, comparator_errors))
    c = sum(full and (not comparator) for full, comparator in zip(full_errors, comparator_errors))
    discordant = b + c
    if discordant == 0:
        p_value = 1.0
    else:
        tail = sum(math.comb(discordant, k) for k in range(min(b, c) + 1)) / (2**discordant)
        p_value = min(1.0, 2 * tail)
    return McNemarResult(b, c, discordant, p_value)


def holm_adjust(p_values: list[float]) -> list[float]:
    if any(not 0 <= value <= 1 for value in p_values):
        raise ValueError("p-values must be between 0 and 1")
    indexed = sorted(enumerate(p_values), key=lambda item: item[1])
    adjusted_sorted: list[tuple[int, float]] = []
    running = 0.0
    count = len(p_values)
    for rank, (original_index, value) in enumerate(indexed):
        adjusted = min(1.0, (count - rank) * value)
        running = max(running, adjusted)
        adjusted_sorted.append((original_index, running))
    result = [0.0] * count
    for original_index, adjusted in adjusted_sorted:
        result[original_index] = adjusted
    return result
