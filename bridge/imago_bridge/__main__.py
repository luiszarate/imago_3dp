"""Entry point: ``python -m imago_bridge``.

Loads settings from the environment, authenticates against Odoo, then runs the
poll/push cycle until SIGTERM or SIGINT. Logs go to stdout.
"""
import logging
import signal
import sys
import threading
from typing import Optional

from . import __version__
from .config import ConfigError, SecretFilter, Settings, load_settings
from .odoo_client import AuthenticationError, OdooClient
from .service import BridgeService

_logger = logging.getLogger("imago_bridge")

EXIT_OK = 0
EXIT_CONFIG = 2
EXIT_AUTH = 3


def setup_logging(level: str, secret: Optional[str] = None) -> None:
    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(name)s: %(message)s"))
    if secret:
        handler.addFilter(SecretFilter(secret))
    root = logging.getLogger()
    root.handlers[:] = [handler]
    root.setLevel(level)


def install_signal_handlers(stop: threading.Event) -> None:
    def _handle(signum, _frame) -> None:
        _logger.info("Señal %s recibida: cerrando el puente.", signal.Signals(signum).name)
        stop.set()

    signal.signal(signal.SIGTERM, _handle)
    signal.signal(signal.SIGINT, _handle)


def run(settings: Settings, stop: threading.Event) -> int:
    client = OdooClient(settings)
    service = BridgeService(client)
    _logger.info(
        "imago-3dp-bridge %s: Odoo %s, base %s, usuario %s.",
        __version__, settings.odoo_url, settings.odoo_db, settings.odoo_login,
    )
    try:
        service.run(stop)
    except AuthenticationError as error:
        _logger.error("%s Revise ODOO_LOGIN / ODOO_API_KEY.", error)
        return EXIT_AUTH
    finally:
        service.close()
    _logger.info("Puente detenido.")
    return EXIT_OK


def main() -> int:
    try:
        settings = load_settings()
    except ConfigError as error:
        setup_logging("INFO")
        _logger.error("Configuración inválida: %s", error)
        return EXIT_CONFIG
    setup_logging(settings.log_level, settings.odoo_api_key)
    stop = threading.Event()
    install_signal_handlers(stop)
    return run(settings, stop)


if __name__ == "__main__":
    sys.exit(main())
