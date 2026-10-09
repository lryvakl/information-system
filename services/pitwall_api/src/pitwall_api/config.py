from f1_common.settings import BaseServiceSettings, DatabaseSettings


class ApiSettings(BaseServiceSettings, DatabaseSettings):
    service_name: str = "pitwall-api"
    port: int = 8000
