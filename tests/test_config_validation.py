import os
from importlib import reload

import config


def test_valid_config_has_no_errors(monkeypatch):
    monkeypatch.setenv("DOCARO_SERVER_PORT", "5001")
    reload(config)
    errs = config.Config.validate_runtime_configuration()
    assert isinstance(errs, list)


def test_invalid_port_detected(monkeypatch):
    monkeypatch.setenv("DOCARO_SERVER_PORT", "70000")
    reload(config)
    errs = config.Config.validate_runtime_configuration()
    assert any("PORT" in e.upper() for e in errs)


def test_invalid_autosort_conf(monkeypatch):
    monkeypatch.setenv("DOCARO_AUTOSORT_CONF", "2.5")
    reload(config)
    errs = config.Config.validate_runtime_configuration()
    assert any("AUTOSORT_CONF" in e for e in errs)
