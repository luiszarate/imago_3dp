"""Odoo 14 JSON-RPC client (D-12): ``/jsonrpc`` with the technical user's API key."""
import itertools
import json
import logging
import urllib.request
from typing import Any, Dict, List, Optional
from urllib.error import HTTPError, URLError

from .config import Settings
from .schema import clean_text

_logger = logging.getLogger(__name__)

TIMEOUT_SECONDS = 10.0
MAX_REPLY_BYTES = 1024 * 1024
BRIDGE_MODEL = "imago.printer.bridge"
MAX_ERROR_CHARS = 300


class OdooError(Exception):
    """Base class of every Odoo client error. Messages never include the API key."""


class OdooUnavailable(OdooError):
    """Network, HTTP or protocol failure: retry later with backoff."""


class OdooRpcError(OdooError):
    """Odoo answered with a JSON-RPC error (AccessError, ValidationError, ...)."""

    def __init__(self, message: str, error_name: Optional[str] = None) -> None:
        super().__init__(message)
        self.error_name = error_name


class AuthenticationError(OdooError):
    """Login or API key rejected: fix the configuration, retrying will not help."""


def _summarise_error(error: Any, secret: str) -> OdooRpcError:
    """Short message and exception name only; the server traceback is not kept."""
    error = error if isinstance(error, dict) else {}
    data = error.get("data") if isinstance(error.get("data"), dict) else {}
    message = str(data.get("message") or error.get("message") or "error")
    if secret:
        message = message.replace(secret, "***")
    name = data.get("name")
    return OdooRpcError(
        clean_text(message, MAX_ERROR_CHARS) or "error",
        clean_text(name, MAX_ERROR_CHARS) if isinstance(name, str) else None,
    )


class OdooClient:
    def __init__(self, settings: Settings, opener: Optional[urllib.request.OpenerDirector] = None) -> None:
        self._settings = settings
        self._opener = opener or urllib.request.build_opener()
        self._ids = itertools.count(1)
        self._uid: Optional[int] = None

    @property
    def uid(self) -> Optional[int]:
        return self._uid

    def _post(self, body: bytes) -> Dict[str, Any]:
        request = urllib.request.Request(
            self._settings.jsonrpc_url,
            data=body,
            method="POST",
            headers={"Content-Type": "application/json", "User-Agent": "imago-3dp-bridge"},
        )
        try:
            with self._opener.open(request, timeout=TIMEOUT_SECONDS) as response:
                raw = response.read(MAX_REPLY_BYTES + 1)
        except HTTPError as error:
            raise OdooUnavailable("Odoo respondió HTTP %d" % error.code) from None
        except (URLError, OSError) as error:
            raise OdooUnavailable("Odoo no responde (%s)" % type(error).__name__) from None
        if len(raw) > MAX_REPLY_BYTES:
            raise OdooUnavailable("respuesta de Odoo demasiado grande")
        try:
            reply = json.loads(raw.decode("utf-8"))
        except ValueError:
            raise OdooUnavailable("respuesta de Odoo no es JSON") from None
        if not isinstance(reply, dict):
            raise OdooUnavailable("respuesta JSON-RPC sin formato de objeto")
        return reply

    def call(self, service: str, method: str, args: List[Any]) -> Any:
        """One JSON-RPC ``call``; raise OdooRpcError when Odoo returns ``error``."""
        body = json.dumps({
            "jsonrpc": "2.0",
            "method": "call",
            "params": {"service": service, "method": method, "args": args},
            "id": next(self._ids),
        }).encode("utf-8")
        reply = self._post(body)
        if reply.get("error") is not None:
            raise _summarise_error(reply["error"], self._settings.odoo_api_key)
        if "result" not in reply:
            raise OdooUnavailable("respuesta JSON-RPC sin 'result'")
        return reply["result"]

    def authenticate(self) -> int:
        settings = self._settings
        uid = self.call("common", "authenticate", [settings.odoo_db, settings.odoo_login, settings.odoo_api_key, {}])
        if isinstance(uid, bool) or not isinstance(uid, int) or uid <= 0:
            raise AuthenticationError(
                "Odoo rechazó el usuario %r o su API key en la base %r." % (settings.odoo_login, settings.odoo_db)
            )
        self._uid = uid
        return uid

    def execute_kw(self, method: str, args: List[Any]) -> Any:
        if self._uid is None:
            self.authenticate()
        settings = self._settings
        return self.call(
            "object", "execute_kw",
            [settings.odoo_db, self._uid, settings.odoo_api_key, BRIDGE_MODEL, method, args],
        )

    def get_config(self) -> Any:
        return self.execute_kw("get_config", [])

    def push_telemetry(self, payload: Dict[str, Any]) -> Any:
        return self.execute_kw("push_telemetry", [payload])
