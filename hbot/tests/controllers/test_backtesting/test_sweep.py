"""Tests for parameter sweep engine — grid generation, LHS coverage, ranking."""
from __future__ import annotations

import pytest

from controllers.backtesting.sweep import (
    _expand_grid,
    _lhs_samples,
    generate_grid,
)
from controllers.backtesting.types import ParamSpace


class TestExpandGrid:
    def test_grid_mode(self):
        space = ParamSpace(name="x", mode="grid", values=[1, 2, 3])
        assert _expand_grid(space) == [1, 2, 3]

    def test_range_mode(self):
        space = ParamSpace(name="x", mode="range", min_val=0, max_val=1.0, step=0.5)
        vals = _expand_grid(space)
        assert len(vals) == 3  # 0, 0.5, 1.0
        assert vals[0] == pytest.approx(0.0)
        assert vals[-1] == pytest.approx(1.0)

    def test_log_range_mode(self):
        space = ParamSpace(name="x", mode="log_range", min_val=1, max_val=100, num_points=3)
        vals = _expand_grid(space)
        assert len(vals) == 3
        assert vals[0] == pytest.approx(1.0)
        assert vals[-1] == pytest.approx(100.0)
        # Middle should be ~10 (geometric mean)
        assert 5 < vals[1] < 20

    def test_invalid_mode(self):
        space = ParamSpace(name="x", mode="magic")
        with pytest.raises(ValueError):
            _expand_grid(space)


class TestGenerateGrid:
    def test_cartesian_product(self):
        spaces = [
            ParamSpace(name="a", mode="grid", values=[1, 2]),
            ParamSpace(name="b", mode="grid", values=["x", "y", "z"]),
        ]
        combos = generate_grid(spaces)
        assert len(combos) == 6  # 2 * 3
        assert {"a": 1, "b": "x"} in combos
        assert {"a": 2, "b": "z"} in combos

    def test_single_param(self):
        spaces = [ParamSpace(name="a", mode="grid", values=[10, 20, 30])]
        combos = generate_grid(spaces)
        assert len(combos) == 3


class TestLHS:
    def test_correct_sample_count(self):
        spaces = [
            ParamSpace(name="a", mode="range", min_val=0, max_val=1),
            ParamSpace(name="b", mode="range", min_val=10, max_val=100),
        ]
        samples = _lhs_samples(spaces, n_samples=20, seed=42)
        assert len(samples) == 20
        assert all("a" in s and "b" in s for s in samples)

    def test_within_bounds(self):
        spaces = [
            ParamSpace(name="x", mode="range", min_val=5.0, max_val=10.0),
        ]
        samples = _lhs_samples(spaces, n_samples=100, seed=42)
        for s in samples:
            assert 5.0 <= s["x"] <= 10.0

    def test_deterministic(self):
        spaces = [ParamSpace(name="x", mode="range", min_val=0, max_val=1)]
        s1 = _lhs_samples(spaces, 10, seed=42)
        s2 = _lhs_samples(spaces, 10, seed=42)
        assert s1 == s2

    def test_different_seed_different_output(self):
        spaces = [ParamSpace(name="x", mode="range", min_val=0, max_val=1)]
        s1 = _lhs_samples(spaces, 10, seed=42)
        s2 = _lhs_samples(spaces, 10, seed=99)
        assert s1 != s2
