from pathlib import Path

from race_engine.config import EngineSettings
from race_engine.sources.base import FallbackRaceSource, RaceSource
from race_engine.sources.openf1 import OpenF1Client, OpenF1ReplaySource, ReplayRace
from race_engine.sources.simulation import SimulatedRaceSource


def build_race_source(settings: EngineSettings) -> RaceSource:
    simulation = SimulatedRaceSource(seed=settings.seed)
    if settings.race_source == "simulation":
        return simulation

    replay = OpenF1ReplaySource(
        client=OpenF1Client(settings.openf1_base_url, cache_dir=Path(settings.openf1_cache_dir)),
        races=[ReplayRace.parse(item) for item in settings.replay_races.split(",") if item.strip()],
    )
    if settings.replay_fallback_to_simulation:
        return FallbackRaceSource(primary=replay, fallback=simulation)
    return replay
