"""Small orchestration helpers."""

from __future__ import annotations

from itertools import count
from typing import Optional

from .episode import Episode, EpisodeProtocolError
from .models import EpisodeResult
from .protocols import BenchmarkCase, Oracle, PlayerBackend


def run_episode(
    player: PlayerBackend,
    case: BenchmarkCase,
    *,
    oracle: Optional[Oracle] = None,
    max_turns: Optional[int] = 100,
) -> EpisodeResult:
    """Run one fresh episode until the Player commits.

    ``max_turns=None`` removes the action-count limit. Unlimited adaptive
    episodes require this setting so no hidden finite cap changes the method.
    """

    if max_turns is not None and (
        isinstance(max_turns, bool) or not isinstance(max_turns, int) or max_turns < 1
    ):
        raise ValueError("max_turns must be positive or None for unlimited")
    if case.definition.budget is None and max_turns is not None:
        raise ValueError("unlimited adaptive episodes require max_turns=None")
    episode = Episode(case, oracle=oracle)
    for _ in (count() if max_turns is None else range(max_turns)):
        action = player.next_action(episode.view())
        episode.apply(action)
        if episode.finished:
            return episode.result
    raise EpisodeProtocolError(
        "player did not commit within max_turns",
        code="max_turns_reached",
    )


__all__ = ["run_episode"]
