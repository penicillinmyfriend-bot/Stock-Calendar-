"""Tests for the session budget hard stop."""

import unittest
from types import SimpleNamespace

from agentcore.budget import Budget


class FakeClock:
    """A controllable monotonic clock for deterministic time tests."""

    def __init__(self):
        self.t = 0.0

    def __call__(self):
        return self.t

    def advance(self, seconds):
        self.t += seconds


class IterationBudgetTests(unittest.TestCase):
    def test_loop_stops_after_exact_iterations(self):
        budget = Budget(max_iterations=3, clock=FakeClock()).start()
        loops = 0
        while budget.should_continue():
            loops += 1
            budget.tick()
            if loops > 100:  # safety net so a bug can't hang the test
                self.fail("budget never stopped")
        self.assertEqual(loops, 3)
        self.assertTrue(budget.exhausted())
        self.assertIn("iteration budget", budget.stop_reason())

    def test_remaining_iterations(self):
        budget = Budget(max_iterations=5).start()
        budget.tick()
        budget.tick()
        self.assertEqual(budget.remaining()["iterations"], 3)


class TimeBudgetTests(unittest.TestCase):
    def test_hard_stop_when_time_exhausted(self):
        clock = FakeClock()
        budget = Budget(max_minutes=1, clock=clock).start()  # 60 seconds
        self.assertTrue(budget.should_continue())
        clock.advance(59)
        self.assertTrue(budget.should_continue())
        clock.advance(2)  # now 61s > 60s
        self.assertFalse(budget.should_continue())
        self.assertTrue(budget.exhausted())
        self.assertIn("time budget", budget.stop_reason())

    def test_loop_respects_time_budget(self):
        clock = FakeClock()
        budget = Budget(max_minutes=1, clock=clock).start()
        iterations = 0
        while budget.should_continue():
            iterations += 1
            clock.advance(20)  # each iteration "takes" 20s
            budget.tick()
            if iterations > 100:
                self.fail("time budget never stopped the loop")
        # 0->20->40->60 : stops once elapsed >= 60
        self.assertEqual(iterations, 3)


class CombinedAndGuardrailTests(unittest.TestCase):
    def test_whichever_is_first_iterations(self):
        clock = FakeClock()
        budget = Budget(max_minutes=10, max_iterations=2, clock=clock).start()
        budget.tick()
        budget.tick()
        self.assertTrue(budget.exhausted())
        self.assertIn("iteration", budget.stop_reason())

    def test_requires_at_least_one_limit(self):
        with self.assertRaises(ValueError):
            Budget()

    def test_agent_cannot_extend_budget(self):
        budget = Budget(max_iterations=1).start()
        # Limits are read-only properties: no setter, no extend method.
        self.assertFalse(hasattr(budget, "extend"))
        self.assertFalse(hasattr(budget, "set_max_iterations"))
        with self.assertRaises(AttributeError):
            budget.max_iterations = 999  # type: ignore[misc]

    def test_from_config_defaults(self):
        cfg = SimpleNamespace(
            session=SimpleNamespace(default_minutes=7, default_iterations=9)
        )
        budget = Budget.from_config(cfg)
        self.assertEqual(budget.max_minutes, 7)
        self.assertEqual(budget.max_iterations, 9)

    def test_from_config_cli_override(self):
        cfg = SimpleNamespace(
            session=SimpleNamespace(default_minutes=7, default_iterations=9)
        )
        budget = Budget.from_config(cfg, iterations=2)
        self.assertEqual(budget.max_iterations, 2)
        self.assertIsNone(budget.max_minutes)  # only the override applies


if __name__ == "__main__":
    unittest.main()
