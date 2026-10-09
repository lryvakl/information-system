"""REST routes. Authentication happens at the gateway; identity arrives in headers."""

from typing import Annotated

from fastapi import APIRouter, Depends, Header, HTTPException, Path, Query, Request, status
from fastapi.responses import JSONResponse

from pitwall_api.schemas import (
    ChampionshipStanding,
    Lap,
    Me,
    PitStopView,
    Race,
    RaceEventView,
    Standing,
)
from pitwall_api.service import PitwallService


def current_user(
    x_user: Annotated[str | None, Header()] = None,
    x_role: Annotated[str | None, Header()] = None,
) -> Me:
    """Defense in depth: reject requests that did not pass through the auth gateway."""
    if not x_user or not x_role:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Request must go through the gateway")
    return Me(username=x_user, role=x_role)


def get_service(request: Request) -> PitwallService:
    return request.app.state.pitwall_service


ServiceDep = Annotated[PitwallService, Depends(get_service)]
RaceRef = Annotated[str, Path(description="Numeric race id or 'latest'")]

router = APIRouter(prefix="/api", tags=["pitwall"], dependencies=[Depends(current_user)])


def race_not_found_handler(_request: Request, exc: Exception) -> JSONResponse:
    return JSONResponse({"detail": f"Race '{exc}' not found"}, status_code=status.HTTP_404_NOT_FOUND)


@router.get("/me", response_model=Me)
def me(user: Annotated[Me, Depends(current_user)]) -> Me:
    return user


@router.get("/races", response_model=list[Race])
def list_races(service: ServiceDep, limit: Annotated[int, Query(ge=1, le=100)] = 20) -> list[dict]:
    return service.races(limit)


@router.get("/races/{race_ref}", response_model=Race)
def get_race(race_ref: RaceRef, service: ServiceDep) -> dict:
    return service.race(race_ref)


@router.get("/races/{race_ref}/standings", response_model=list[Standing])
def standings(race_ref: RaceRef, service: ServiceDep) -> list[dict]:
    return service.standings(race_ref)


@router.get("/races/{race_ref}/pit-stops", response_model=list[PitStopView])
def pit_stops(race_ref: RaceRef, service: ServiceDep) -> list[dict]:
    return service.pit_stops(race_ref)


@router.get("/races/{race_ref}/drivers/{driver_code}/laps", response_model=list[Lap])
def driver_laps(race_ref: RaceRef, driver_code: str, service: ServiceDep) -> list[dict]:
    return service.driver_laps(race_ref, driver_code)


@router.get("/races/{race_ref}/events", response_model=list[RaceEventView])
def events(
    race_ref: RaceRef,
    service: ServiceDep,
    event_type: Annotated[str | None, Query(alias="type")] = None,
    limit: Annotated[int, Query(ge=1, le=500)] = 100,
) -> list[dict]:
    return service.events(race_ref, event_type, limit)


@router.get("/championship", response_model=list[ChampionshipStanding])
def championship(service: ServiceDep) -> list[dict]:
    return service.championship()
