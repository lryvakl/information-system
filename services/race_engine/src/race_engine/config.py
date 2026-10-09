from typing import Literal

from f1_common.settings import BaseServiceSettings, DatabaseSettings, MessagingSettings


class EngineSettings(BaseServiceSettings, DatabaseSettings, MessagingSettings):
    service_name: str = "race-engine"
    metrics_port: int = 9100

    race_source: Literal["simulation", "replay"] = "simulation"
    # Comma-separated "<year>:<OpenF1 circuit_short_name>" list, replayed in a loop.
    replay_races: str = "2024:Monza,2024:Silverstone,2024:Spa-Francorchamps"
    replay_fallback_to_simulation: bool = True
    openf1_base_url: str = "https://api.openf1.org/v1"
    openf1_cache_dir: str = "/data/openf1"

    speed_factor: float = 20.0
    telemetry_tick_seconds: float = 1.0
    telemetry_retention_minutes: int = 30
    pause_between_races_seconds: float = 15.0
    seed: int | None = None
