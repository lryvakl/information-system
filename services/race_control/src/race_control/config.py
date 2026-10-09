from f1_common.settings import BaseServiceSettings, DatabaseSettings, MessagingSettings


class RaceControlSettings(BaseServiceSettings, DatabaseSettings, MessagingSettings):
    service_name: str = "race-control"
    metrics_port: int = 9101
    queue_name: str = "race-control"
    prefetch_count: int = 50
