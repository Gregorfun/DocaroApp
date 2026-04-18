from __future__ import annotations

import desktop_app


def test_desktop_simple_worker_disables_signal_handlers():
    worker = object.__new__(desktop_app.DesktopSimpleWorker)
    assert worker._install_signal_handlers() is None