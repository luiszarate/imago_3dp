"""Bridge settings from environment variables. The API key is never logged or repr'd."""
import logging
import os
from dataclasses import dataclass, field
from typing import Mapping, Optional
from urllib.parse import urlsplit

REQUIRED_VARS = ("ODOO_URL", "ODOO_DB", "ODOO_LOGIN")
LOG_LEVELS = ("DEBUG", "INFO", "WARNING", "ERROR")
TRUE_VALUES = ("1", "true", "yes", "si", "sí")


class ConfigError(ValueError):
    """Missing or invalid environment configuration (the bridge refuses to start)."""


@dataclass(frozen=True)
class Settings:
    odoo_url: str
    odoo_db: str
    odoo_login: str
    odoo_api_key: str = field(repr=False)
    log_level: str = "INFO"

    @property
    def jsonrpc_url(self) -> str:
        return self.odoo_url.rstrip("/") + "/jsonrpc"


def _read_api_key(env: Mapping[str, str]) -> str:
    """ODOO_API_KEY, or the content of ODOO_API_KEY_FILE (Docker secret)."""
    key = env.get("ODOO_API_KEY", "").strip()
    key_file = env.get("ODOO_API_KEY_FILE", "").strip()
    if not key and key_file:
        try:
            with open(key_file, encoding="utf-8") as handle:
                key = handle.read().strip()
        except OSError as error:
            raise ConfigError("No se pudo leer ODOO_API_KEY_FILE (%s)." % error.strerror) from None
    if not key:
        raise ConfigError("Falta la variable de entorno ODOO_API_KEY (o ODOO_API_KEY_FILE).")
    return key


def _check_url(url: str, allow_http: bool) -> str:
    try:
        parts = urlsplit(url)
    except ValueError:
        raise ConfigError("ODOO_URL no es una URL válida.") from None
    if parts.scheme not in ("https", "http") or not parts.hostname:
        raise ConfigError("ODOO_URL debe ser https://servidor (p. ej. https://erp.imago.aero).")
    if parts.scheme == "http" and not allow_http:
        raise ConfigError(
            "ODOO_URL usa http: la API key viajaría sin cifrar. Use https, o defina "
            "BRIDGE_ALLOW_INSECURE_HTTP=1 solo para una base de pruebas local."
        )
    if parts.username or parts.password or parts.query or parts.fragment:
        raise ConfigError("ODOO_URL no debe llevar usuario, contraseña, parámetros ni fragmento.")
    return url.rstrip("/")


def load_settings(env: Optional[Mapping[str, str]] = None) -> Settings:
    """Read and validate the settings; raise ConfigError with a clear message (fail fast)."""
    env = os.environ if env is None else env
    missing = [name for name in REQUIRED_VARS if not env.get(name, "").strip()]
    if missing:
        raise ConfigError("Faltan variables de entorno: %s." % ", ".join(missing))
    api_key = _read_api_key(env)
    allow_http = env.get("BRIDGE_ALLOW_INSECURE_HTTP", "").strip().lower() in TRUE_VALUES
    level = env.get("BRIDGE_LOG_LEVEL", "INFO").strip().upper() or "INFO"
    if level not in LOG_LEVELS:
        raise ConfigError("BRIDGE_LOG_LEVEL debe ser uno de: %s." % ", ".join(LOG_LEVELS))
    return Settings(
        odoo_url=_check_url(env["ODOO_URL"].strip(), allow_http),
        odoo_db=env["ODOO_DB"].strip(),
        odoo_login=env["ODOO_LOGIN"].strip(),
        odoo_api_key=api_key,
        log_level=level,
    )


class SecretFilter(logging.Filter):
    """Defence in depth: redacts the API key if any log record ever contains it."""

    def __init__(self, secret: str) -> None:
        super().__init__()
        self._secret = secret

    def filter(self, record: logging.LogRecord) -> bool:
        if self._secret and self._secret in record.getMessage():
            record.msg = record.getMessage().replace(self._secret, "***")
            record.args = ()
        return True
