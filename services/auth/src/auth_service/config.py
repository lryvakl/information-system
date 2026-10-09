from pydantic import SecretStr

from f1_common.settings import BaseServiceSettings


class AuthSettings(BaseServiceSettings):
    service_name: str = "auth"
    port: int = 8000

    database_path: str = "/data/auth.db"

    jwt_secret: SecretStr
    jwt_algorithm: str = "HS256"
    jwt_ttl_minutes: int = 120

    admin_username: str = "admin"
    admin_password: SecretStr

    cookie_name: str = "f1_session"
    cookie_secure: bool = False
    default_redirect: str = "/grafana/"
