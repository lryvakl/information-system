"""Translates the internal race model into integration events for RabbitMQ."""

from f1_common.events import (
    ClassificationEntry,
    FastestLap,
    LapCompleted,
    Overtake,
    PitStop,
    RaceControl,
    RaceEvent,
    RaceFinished,
    RaceStarted,
    Retirement,
)
from race_engine.domain.models import LapFrame, RaceInfo
from race_engine.domain.standings import FastestLapRecord, StandingEntry, StandingsUpdate


class RaceEventFactory:
    def race_started(self, race_id: int, info: RaceInfo) -> RaceStarted:
        return RaceStarted(
            race_id=race_id,
            lap=0,
            name=info.name,
            circuit=info.circuit.name,
            total_laps=info.total_laps,
            source=info.source.value,
            drivers=[driver.code for driver in info.drivers],
        )

    def lap_events(self, race_id: int, info: RaceInfo, frame: LapFrame, standings: StandingsUpdate) -> list[RaceEvent]:
        lap = frame.lap
        events: list[RaceEvent] = [
            RaceControl(race_id=race_id, lap=lap, category=m.category, message=m.message, flag=m.flag)
            for m in frame.messages
        ]
        events += [
            Retirement(race_id=race_id, lap=lap, driver=r.driver_code, reason=r.reason) for r in frame.retirements
        ]
        for driver_lap in frame.laps:
            entry = standings.entry(driver_lap.driver_code)
            events.append(
                LapCompleted(
                    race_id=race_id,
                    lap=lap,
                    driver=driver_lap.driver_code,
                    position=entry.position,
                    lap_time=driver_lap.lap_time,
                    gap_to_leader=round(entry.gap_to_leader, 3),
                    compound=driver_lap.compound.value,
                    tyre_age=driver_lap.tyre_age,
                    tyre_wear=driver_lap.tyre_wear,
                )
            )
            if driver_lap.pit_stop:
                events.append(
                    PitStop(
                        race_id=race_id,
                        lap=lap,
                        driver=driver_lap.driver_code,
                        team=info.driver(driver_lap.driver_code).team.name,
                        pit_lane_time=driver_lap.pit_stop.pit_lane_time,
                        stationary_time=driver_lap.pit_stop.stationary_time,
                        compound_out=driver_lap.pit_stop.compound_out.value,
                    )
                )
        events += [
            Overtake(race_id=race_id, lap=lap, driver=o.driver_code, overtaken=o.overtaken_code, position=o.position)
            for o in standings.overtakes
        ]
        if standings.new_fastest_lap:
            events.append(
                FastestLap(
                    race_id=race_id,
                    lap=lap,
                    driver=standings.new_fastest_lap.driver_code,
                    lap_time=standings.new_fastest_lap.lap_time,
                )
            )
        return events

    def race_finished(
        self,
        race_id: int,
        info: RaceInfo,
        classification: tuple[StandingEntry, ...],
        fastest_lap: FastestLapRecord | None,
    ) -> RaceFinished:
        return RaceFinished(
            race_id=race_id,
            lap=info.total_laps,
            classification=[
                ClassificationEntry(
                    position=entry.position,
                    driver=entry.driver_code,
                    team=info.driver(entry.driver_code).team.name,
                    laps=entry.laps,
                    total_time=None if entry.retired else round(entry.total_time, 3),
                    finished=not entry.retired,
                )
                for entry in classification
            ],
            fastest_lap_driver=fastest_lap.driver_code if fastest_lap else None,
        )
