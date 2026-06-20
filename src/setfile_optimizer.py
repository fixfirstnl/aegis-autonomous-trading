import json
import random
from pathlib import Path
from typing import Dict, List, Any, Tuple
import structlog

from config import config, SETFILES_DIR

logger = structlog.get_logger()


class SetfileOptimizer:
    """Optimizes EA parameters by testing parameter grids."""

    def __init__(self, base_params: Dict[str, Any] = None):
        self.base_params = base_params or {}

    def generate_grid(self, param_ranges: Dict[str, Tuple[float, float, float]]) -> List[Dict[str, Any]]:
        """Generate parameter combinations from ranges.

        Args:
            param_ranges: {name: (min, max, step)}

        Returns:
            List of parameter dicts.
        """
        import itertools
        keys = list(param_ranges.keys())
        ranges = []
        for k in keys:
            min_v, max_v, step = param_ranges[k]
            values = []
            v = min_v
            while v <= max_v:
                values.append(round(v, 6))
                v += step
            ranges.append(values)

        grids = []
        for combo in itertools.product(*ranges):
            params = dict(self.base_params)
            for i, k in enumerate(keys):
                params[k] = combo[i]
            grids.append(params)

        logger.info("grid_generated", combinations=len(grids))
        return grids

    def random_search(self, param_ranges: Dict[str, Tuple[float, float]], n_samples: int = 20) -> List[Dict[str, Any]]:
        """Random search over parameter space."""
        samples = []
        for _ in range(n_samples):
            params = dict(self.base_params)
            for k, (min_v, max_v) in param_ranges.items():
                params[k] = round(random.uniform(min_v, max_v), 6)
            samples.append(params)
        logger.info("random_search_generated", samples=n_samples)
        return samples

    def evaluate(self, params: Dict[str, Any], backtest_result: Dict[str, float]) -> float:
        """Score a parameter set based on backtest metrics.

        Returns:
            Fitness score (higher is better).
        """
        profit = backtest_result.get("profit", 0)
        drawdown = backtest_result.get("max_drawdown", 100)
        winrate = backtest_result.get("winrate", 0)
        sharpe = backtest_result.get("sharpe", 0)

        # Penalize high drawdown heavily
        dd_penalty = max(0, drawdown - 10) * 10
        score = profit + winrate * 10 + sharpe * 50 - dd_penalty
        return score

    def optimize(self, param_ranges: Dict[str, Any], evaluator_func) -> Dict[str, Any]:
        """Run optimization and return best params."""
        grids = self.random_search(param_ranges, n_samples=20)
        best_score = -float('inf')
        best_params = None

        for params in grids:
            # Mock evaluation - replace with real backtest
            result = evaluator_func(params)
            score = self.evaluate(params, result)
            if score > best_score:
                best_score = score
                best_params = params

        logger.info("optimization_complete", best_score=best_score)
        return best_params or self.base_params

    def save_best(self, name: str, params: Dict[str, Any]) -> None:
        """Save optimized params to setfile."""
        config.save_setfile(f"{name}_optimized", params)

    def load_base(self, name: str) -> Dict[str, Any]:
        """Load base setfile."""
        return config.load_setfile(name)
