import random

from race_engine.domain.models import Compound, RaceSourceKind
from race_engine.domain.standings import StandingsCalculator
from race_engine.domain.tyres import TyreModel
from race_engine.sources.catalog import TRACKS
from race_engine.sources.simulation import SimulatedRaceSource
from race_engine.sources.simulation.strategy import PitStrategy


def test_tyres_wear_and_slow_down_with_age() -> None:
    tyres = TyreModel()

    assert tyres.wear(Compound.SOFT, 10) > tyres.wear(Compound.HARD, 10)
    assert tyres.lap_time_penalty(Compound.MEDIUM, 25) > tyres.lap_time_penalty(Compound.MEDIUM, 5)
    assert tyres.lap_time_penalty(Compound.SOFT, 0) < tyres.lap_time_penalty(Compound.HARD, 0)
    assert tyres.wear(Compound.SOFT, 1000) == 100.0


def test_strategy_enforces_second_compound_near_the_end() -> None:
    strategy = PitStrategy(TyreModel(), random.Random(1))

    assert strategy.wants_pit(Compound.HARD, 3, {Compound.HARD}, laps_remaining=3, safety_car=False, threshold=70)
    assert not strategy.wants_pit(Compound.HARD, 3, {Compound.HARD, Compound.MEDIUM}, 3, False, 70)
    assert not strategy.wants_pit(Compound.SOFT, 40, {Compound.SOFT}, laps_remaining=1, safety_car=False, threshold=70)


def test_strategy_picks_softest_compound_that_lasts() -> None:
    strategy = PitStrategy(TyreModel(), random.Random(1))

    assert strategy.choose_compound({Compound.MEDIUM}, laps_remaining=10) == Compound.SOFT
    assert strategy.choose_compound({Compound.SOFT}, laps_remaining=45) == Compound.HARD


def test_simulated_race_is_complete_and_consistent() -> None:
    session = SimulatedRaceSource(tracks=TRACKS[:1], seed=42).next_race()
    info = session.info
    frames = list(session.frames)

    assert info.source is RaceSourceKind.SIMULATION
    assert len(info.drivers) == 20
    assert [frame.lap for frame in frames] == list(range(1, info.total_laps + 1))

    retired = {r.driver_code for frame in frames for r in frame.retirements}
    finishers = {lap.driver_code for lap in frames[-1].laps}
    assert finishers | retired == {driver.code for driver in info.drivers}
    assert not finishers & retired

    for frame in frames:
        assert all(60 < lap.lap_time < 200 for lap in frame.laps)

    calc = StandingsCalculator([d.code for d in info.drivers])
    for frame in frames:
        calc.apply(frame)
    assert calc.classification()[0].driver_code in finishers


def test_every_finisher_uses_two_compounds() -> None:
    session = SimulatedRaceSource(tracks=TRACKS[:1], seed=7).next_race()
    compounds: dict[str, set[Compound]] = {}
    frames = list(session.frames)
    for frame in frames:
        for lap in frame.laps:
            compounds.setdefault(lap.driver_code, set()).add(lap.compound)
            if lap.pit_stop:
                compounds[lap.driver_code].add(lap.pit_stop.compound_out)

    for lap in frames[-1].laps:
        assert len(compounds[lap.driver_code]) >= 2, lap.driver_code


def test_same_seed_gives_same_race() -> None:
    first = [lap.lap_time for f in SimulatedRaceSource(seed=3).next_race().frames for lap in f.laps]
    second = [lap.lap_time for f in SimulatedRaceSource(seed=3).next_race().frames for lap in f.laps]

    assert first == second
