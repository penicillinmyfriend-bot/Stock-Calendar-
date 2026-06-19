"""Session budget with a hard stop.

A :class:`Budget` bounds a run by wall-clock minutes, by iteration count, or
both -- whichever limit is reached first ends the run. The limits are set once
(from the CLI or config) and are exposed only as read-only properties: there is
**no** method to raise them, so the running agent cannot extend its own budget.

The clock is injectable so the hard-stop behaviour can be unit-tested without
real time passing.
"""

from __future__ import annotations

import time
from typing import Any, Callable, Dict, Optional


class Budget:
    """Tracks elapsed time and iterations against fixed, read-only limits."""

    def __init__(
        self,
        *,
        max_minutes: Optional[float] = None,
        max_iterations: Optional[int] = None,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        if max_minutes is None and max_iterations is None:
            raise ValueError("a budget needs a time limit, an iteration limit, or both")
        if max_minutes is not None and max_minutes <= 0:
            raise ValueError("max_minutes must be positive")
        if max_iterations is not None and max_iterations <= 0:
            raise ValueError("max_iterations must be positive")
        # Stored privately; no setter is ever exposed.
        self.__max_seconds = (max_minutes * 60.0) if max_minutes is not None else None
        self.__max_iterations = max_iterations
        self.__clock = clock
        self.__start: Optional[float] = None
        self.__iterations = 0

    # --- read-only view ---------------------------------------------------
    @property
    def max_seconds(self) -> Optional[float]:
        return self.__max_seconds

    @property
    def max_minutes(self) -> Optional[float]:
        return None if self.__max_seconds is None else self.__max_seconds / 60.0

    @property
    def max_iterations(self) -> Optional[int]:
        return self.__max_iterations

    @property
    def iterations(self) -> int:
        return self.__iterations

    @property
    def started(self) -> bool:
        return self.__start is not None

    @property
    def elapsed_seconds(self) -> float:
        if self.__start is None:
            return 0.0
        return self.__clock() - self.__start

    # --- lifecycle --------------------------------------------------------
    def start(self) -> "Budget":
        self.__start = self.__clock()
        return self

    def tick(self) -> None:
        """Record that one iteration has completed."""
        self.__iterations += 1

    # --- checks -----------------------------------------------------------
    def time_exhausted(self) -> bool:
        return self.__max_seconds is not None and self.elapsed_seconds >= self.__max_seconds

    def iterations_exhausted(self) -> bool:
        return self.__max_iterations is not None and self.__iterations >= self.__max_iterations

    def exhausted(self) -> bool:
        return self.time_exhausted() or self.iterations_exhausted()

    def should_continue(self) -> bool:
        return not self.exhausted()

    def stop_reason(self) -> Optional[str]:
        """Human-readable reason the budget is spent, or None if it isn't."""
        if self.time_exhausted():
            return f"time budget reached ({self.max_minutes:.1f} min)"
        if self.iterations_exhausted():
            return f"iteration budget reached ({self.__max_iterations} iterations)"
        return None

    def remaining(self) -> Dict[str, Any]:
        rem_secs = (
            None if self.__max_seconds is None
            else max(0.0, self.__max_seconds - self.elapsed_seconds)
        )
        rem_iters = (
            None if self.__max_iterations is None
            else max(0, self.__max_iterations - self.__iterations)
        )
        return {"seconds": rem_secs, "iterations": rem_iters}

    def __str__(self) -> str:
        parts = []
        if self.__max_seconds is not None:
            parts.append(f"{self.elapsed_seconds:.0f}/{self.__max_seconds:.0f}s")
        if self.__max_iterations is not None:
            parts.append(f"{self.__iterations}/{self.__max_iterations} iters")
        return "budget(" + ", ".join(parts) + ")"

    # --- construction from config ----------------------------------------
    @classmethod
    def from_config(
        cls,
        config: Any = None,
        *,
        minutes: Optional[float] = None,
        iterations: Optional[int] = None,
        clock: Callable[[], float] = time.monotonic,
    ) -> "Budget":
        """Build a budget from CLI overrides, falling back to config defaults.

        If the caller passes ``minutes`` and/or ``iterations``, exactly those
        limits are used. If neither is given, the config's default minutes *and*
        default iterations both apply.
        """
        if minutes is None and iterations is None:
            session = getattr(config, "session", None)
            minutes = getattr(session, "default_minutes", 10)
            iterations = getattr(session, "default_iterations", 25)
        return cls(max_minutes=minutes, max_iterations=iterations, clock=clock)
