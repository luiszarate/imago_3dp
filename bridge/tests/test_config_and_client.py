"""Environment settings (fail fast, key never shown) and the JSON-RPC client."""
import json
import logging
from urllib.error import HTTPError, URLError

import pytest
from conftest import FakeOpener

from imago_bridge.config import ConfigError, SecretFilter, load_settings
from imago_bridge.odoo_client import (
    AuthenticationError,
    OdooClient,
    OdooRpcError,
    OdooUnavailable,
)

KEY = "0123456789abcdef-FAKE-KEY"
ENV = {"ODOO_URL": "https://erp.example.test/", "ODOO_DB": "manuf_test", "ODOO_LOGIN": "bridge@x", "ODOO_API_KEY": KEY}


# ----------------------------------------------------------------- settings
def test_settings_from_env():
    settings = load_settings(ENV)
    assert settings.jsonrpc_url == "https://erp.example.test/jsonrpc"
    assert settings.log_level == "INFO"
    assert KEY not in repr(settings)


@pytest.mark.parametrize("missing", ["ODOO_URL", "ODOO_DB", "ODOO_LOGIN", "ODOO_API_KEY"])
def test_missing_variable_fails_fast(missing):
    env = {k: v for k, v in ENV.items() if k != missing}
    with pytest.raises(ConfigError) as info:
        load_settings(env)
    assert missing in str(info.value)
    assert KEY not in str(info.value)


def test_api_key_from_file(tmp_path):
    secret = tmp_path / "key"
    secret.write_text(KEY + "\n")
    env = {k: v for k, v in ENV.items() if k != "ODOO_API_KEY"} | {"ODOO_API_KEY_FILE": str(secret)}
    assert load_settings(env).odoo_api_key == KEY


@pytest.mark.parametrize("url", ["http://erp.example.test", "ftp://x", "erp.example.test", "https://u:p@x.test"])
def test_bad_urls_refused(url):
    with pytest.raises(ConfigError):
        load_settings(ENV | {"ODOO_URL": url})


def test_http_needs_explicit_opt_in():
    settings = load_settings(ENV | {"ODOO_URL": "http://localhost:8069", "BRIDGE_ALLOW_INSECURE_HTTP": "1"})
    assert settings.jsonrpc_url == "http://localhost:8069/jsonrpc"


def test_bad_log_level():
    with pytest.raises(ConfigError):
        load_settings(ENV | {"BRIDGE_LOG_LEVEL": "LOUD"})


def test_secret_filter_redacts():
    handler_filter = SecretFilter(KEY)
    record = logging.getLogger("test.secret").makeRecord("t", logging.INFO, __file__, 1, "key=%s", (KEY,), None)
    handler_filter.filter(record)
    assert KEY not in record.getMessage() and "***" in record.getMessage()


# ----------------------------------------------------------------- client
def rpc(result=None, error=None):
    body = {"jsonrpc": "2.0", "id": 1}
    body.update({"error": error} if error else {"result": result})
    return json.dumps(body).encode()


def sent_body(opener, index):
    return json.loads(opener.requests[index][0].data.decode())


def test_authenticate_then_execute_kw():
    opener = FakeOpener(rpc(7), rpc({"config_version": 1}), rpc({"ok": True}))
    client = OdooClient(load_settings(ENV), opener=opener)
    assert client.get_config() == {"config_version": 1}
    assert client.push_telemetry({"printers": []}) == {"ok": True}
    auth, get_config, push = (sent_body(opener, i) for i in range(3))
    assert auth["params"] == {"service": "common", "method": "authenticate",
                              "args": ["manuf_test", "bridge@x", KEY, {}]}
    assert get_config["params"]["args"] == ["manuf_test", 7, KEY, "imago.printer.bridge", "get_config", []]
    assert push["params"]["args"][3:] == ["imago.printer.bridge", "push_telemetry", [{"printers": []}]]
    assert opener.requests[0][0].full_url == "https://erp.example.test/jsonrpc"
    assert opener.requests[0][1] == 10.0


def test_rejected_login_is_authentication_error():
    client = OdooClient(load_settings(ENV), opener=FakeOpener(rpc(False)))
    with pytest.raises(AuthenticationError) as info:
        client.authenticate()
    assert KEY not in str(info.value)


def test_jsonrpc_error_is_typed_and_redacted():
    error = {"code": 200, "message": "Odoo Server Error",
             "data": {"name": "odoo.exceptions.AccessError", "message": "denied for " + KEY, "debug": "trace"}}
    client = OdooClient(load_settings(ENV), opener=FakeOpener(rpc(5), rpc(error=error)))
    with pytest.raises(OdooRpcError) as info:
        client.get_config()
    assert info.value.error_name == "odoo.exceptions.AccessError"
    assert KEY not in str(info.value) and "trace" not in str(info.value)


@pytest.mark.parametrize(
    "failure",
    [URLError("down"), TimeoutError("timed out"), HTTPError("u", 502, "Bad Gateway", {}, None), b"<html>", b"[]",
     b'{"jsonrpc": "2.0"}'],
)
def test_transport_failures_are_unavailable(failure):
    client = OdooClient(load_settings(ENV), opener=FakeOpener(failure))
    with pytest.raises(OdooUnavailable):
        client.authenticate()
