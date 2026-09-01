"""Small orchestration helpers."""

from __future__ import annotations

from typing import Optional

from .episode import Episode, EpisodeProtocolError
from .models import EpisodeResult
from .protocols import BenchmarkCase, Oracle, PlayerBackend


def run_episode(
    player: PlayerBackend,
    case: BenchmarkCase,
    *,
    oracle: Optional[Oracle] = None,
    max_turns: int = 100,
) -> EpisodeResult:
    """Run one fresh episode until the Player commits.

    ``max_turns`` only prevents an ill-behaved Player from issuing infinitely
    many clarification requests.  It is not an experiment budget.
    """

    if max_turns < 1:
        raise ValueError("max_turns must be positive")
    episode = Episode(case, oracle=oracle)
    for _ in range(max_turns):
        action = player.next_action(episode.view())
        episode.apply(action)
        if episode.finished:
            return episode.result
    raise EpisodeProtocolError(
        "player did not commit within max_turns",
        code="max_turns_reached",
    )


__all__ = ["run_episode"]
