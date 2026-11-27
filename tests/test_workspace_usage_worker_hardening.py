"""Workspace worker process boundaries: import path, lifetime, and termination."""

import json
import os
import signal
import subprocess
import sys
import threading
from pathlib import Path

import pytest
from test_workspace_usage_cli import acquisition, command

from sdr_visualizer.cli.main import main
from sdr_visualizer.usage import collector, normalize, sdk_worker


@pytest.fixture(autouse=True)
def no_credentials(monkeypatch):
    for key in ("ORG_ID", "CLIENT_ID", "SECRET", "SCOPES"):
        monkeypatch.delenv(key, raising=False)


class _Spawned(Exception):
    pass


def _capture_argv(monkeypatch, module):
    seen = {}

    def popen(argv, **kwargs):
        seen["argv"], seen["env"] = argv, kwargs["env"]
        raise _Spawned

    with monkeypatch.context() as patch, pytest.raises(_Spawned):
        patch.setattr(module.subprocess, "Popen", popen)
        if module is collector:
            collector._acquire(
                {
                    "platform": "cja",
                    "instance_id": "dv",
                    "org_id": "org",
                    "company_id": None,
                    "config_path": None,
                    "scope": "all",
                    "project_ids": None,
                }
            )
        else:
            sdk_worker.match_projects("cja", [], [{"type": "dimension", "id": "a"}], None)
    return seen["argv"], seen["env"]


@pytest.mark.parametrize("module", [collector, sdk_worker], ids=["api", "sdk"])
def test_worker_ignores_modules_planted_in_working_directory(monkeypatch, tmp_path, module):
    argv, env = _capture_argv(monkeypatch, module)
    assert argv[:3] == [sys.executable, "-P", "-m"]
    marker = tmp_path / "planted-import-ran"
    # Both workers import json before reading their request.
    (tmp_path / "json.py").write_text(f"open({str(marker)!r}, 'w').close()\n")

    def run(worker_argv):
        subprocess.run(
            worker_argv,
            cwd=tmp_path,
            env=env,
            input=b"",
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            timeout=60,
            check=False,
        )

    run(argv)
    assert not marker.exists()
    # Control: the same worker without safe-path mode does run the planted module,
    # so the assertion above proves -P rather than a worker that never started.
    run([argv[0], *argv[2:]])
    assert marker.exists()


@pytest.mark.parametrize(
    "module,lifetime,parent_deadline",
    [(collector, 185, 180), (sdk_worker, 31, 30)],
    ids=["api", "sdk"],
)
def test_worker_arms_own_lifetime_past_parent_deadline(
    monkeypatch, module, lifetime, parent_deadline
):
    calls = []
    monkeypatch.setattr(normalize.signal, "alarm", calls.append)
    monkeypatch.setattr(normalize.signal, "signal", lambda *args: None)
    body = "_api_child" if module is collector else "_match_child"
    monkeypatch.setattr(module, body, lambda: calls.append("body"))
    module._child()
    assert module.WORKER_LIFETIME_SECONDS == lifetime > parent_deadline
    assert calls == [lifetime, "body", 0]


def test_worker_lifetime_cancelled_when_body_raises(monkeypatch):
    calls = []
    monkeypatch.setattr(normalize.signal, "alarm", calls.append)
    monkeypatch.setattr(normalize.signal, "signal", lambda *args: None)

    def body():
        raise RuntimeError

    with pytest.raises(RuntimeError), normalize.bounded_lifetime(5):
        body()
    assert calls == [5, 0]


def test_worker_lifetime_without_sigalrm_relies_on_parent(monkeypatch):
    monkeypatch.delattr(normalize.signal, "alarm")
    with normalize.bounded_lifetime(5):
        pass


@pytest.mark.skipif(not hasattr(signal, "alarm"), reason="SIGALRM unavailable")
def test_orphaned_worker_ends_itself_at_lifetime(tmp_path):
    code = (
        "import time\n"
        "from sdr_visualizer.usage.normalize import bounded_lifetime\n"
        "with bounded_lifetime(1):\n"
        "    time.sleep(30)\n"
    )
    completed = subprocess.run(
        [sys.executable, "-c", code],
        env={**os.environ, "PYTHONPATH": str(Path(normalize.__file__).resolve().parents[2])},
        timeout=20,
        check=False,
    )
    assert completed.returncode == -signal.SIGALRM


@pytest.mark.skipif(not hasattr(signal, "pthread_sigmask"), reason="signal masks unavailable")
def test_orphaned_worker_lifetime_survives_inherited_sigalrm_ignore_and_block(tmp_path):
    code = (
        "import signal, subprocess, sys\n"
        "signal.signal(signal.SIGALRM, signal.SIG_IGN)\n"
        "signal.pthread_sigmask(signal.SIG_BLOCK, {signal.SIGALRM})\n"
        "child = (\n"
        "    'import time\\n'\n"
        "    'from sdr_visualizer.usage.normalize import bounded_lifetime\\n'\n"
        "    'with bounded_lifetime(1):\\n'\n"
        "    '    time.sleep(30)\\n'\n"
        ")\n"
        "sys.exit(-subprocess.run([sys.executable, '-c', child], timeout=20).returncode)\n"
    )
    completed = subprocess.run(
        [sys.executable, "-c", code],
        env={**os.environ, "PYTHONPATH": str(Path(normalize.__file__).resolve().parents[2])},
        timeout=30,
        check=False,
    )
    assert completed.returncode == signal.SIGALRM


def test_termination_routing_keeps_inherited_ignore(monkeypatch):
    number = getattr(signal, "SIGHUP", None)
    if number is None:
        pytest.skip("SIGHUP unavailable")
    previous = signal.signal(number, signal.SIG_IGN)
    try:
        with collector._interrupt_on_termination():
            assert signal.getsignal(number) is signal.SIG_IGN
            assert signal.getsignal(signal.SIGTERM) is collector._interrupt
        assert signal.getsignal(number) is signal.SIG_IGN
    finally:
        signal.signal(number, previous)


def test_termination_routing_restores_when_install_is_interrupted(monkeypatch):
    real_signal = signal.signal
    before = signal.getsignal(signal.SIGTERM)

    def install(number, handler):
        if number != signal.SIGTERM and handler is collector._interrupt:
            raise KeyboardInterrupt
        return real_signal(number, handler)

    monkeypatch.setattr(collector.signal, "signal", install)
    with pytest.raises(KeyboardInterrupt), collector._interrupt_on_termination():
        pass
    assert signal.getsignal(signal.SIGTERM) == before


@pytest.mark.parametrize("name", ["SIGTERM", "SIGHUP"])
def test_termination_signal_becomes_interrupt_then_restores(name):
    number = getattr(signal, name, None)
    if number is None:
        pytest.skip(f"{name} unavailable")
    before = signal.getsignal(number)
    with pytest.raises(KeyboardInterrupt), collector._interrupt_on_termination():
        os.kill(os.getpid(), number)
        threading.Event().wait(5)  # The handler raises before this times out.
    assert signal.getsignal(number) == before


def test_termination_routing_restores_default_for_foreign_handler(monkeypatch):
    installed = {}
    monkeypatch.setattr(collector.signal, "getsignal", lambda number: None)
    monkeypatch.setattr(
        collector.signal, "signal", lambda number, handler: installed.__setitem__(number, handler)
    )
    with collector._interrupt_on_termination():
        assert set(installed.values()) == {collector._interrupt}
    assert set(installed.values()) == {signal.SIG_DFL}


def test_termination_routing_is_inert_off_main_thread(monkeypatch):
    calls = []
    monkeypatch.setattr(collector.signal, "signal", lambda *args: calls.append(args))
    entered = []

    def run():
        with collector._interrupt_on_termination():
            entered.append(True)

    thread = threading.Thread(target=run)
    thread.start()
    thread.join()
    assert entered == [True]
    assert calls == []


def test_termination_routing_skips_signals_platform_lacks(monkeypatch):
    installed = []
    monkeypatch.delattr(collector.signal, "SIGHUP", raising=False)
    monkeypatch.setattr(
        collector.signal, "signal", lambda number, handler: installed.append(number)
    )
    with collector._interrupt_on_termination():
        pass
    assert installed == [signal.SIGTERM, signal.SIGTERM]


def test_parent_termination_during_collection_stops_and_writes_nothing(
    tmp_path, monkeypatch, capsys
):
    def terminated(request):
        os.kill(os.getpid(), signal.SIGTERM)
        threading.Event().wait(5)
        return acquisition()

    monkeypatch.setattr(collector, "_acquire", terminated)
    assert main(command(tmp_path)) == 1
    assert not (tmp_path / "report.html").exists()
    assert not (tmp_path / "report.workspace-usage.json").exists()
    assert "interrupted" in capsys.readouterr().err


def test_unfingerprintable_snapshot_rejected_before_collection(tmp_path, monkeypatch, capsys):
    calls = []
    monkeypatch.setattr(collector, "_acquire", lambda request: calls.append(request))
    args = command(tmp_path)
    snapshot = Path(args[0])
    text = snapshot.read_text()
    assert text.rstrip().endswith("}")
    snapshot.write_text(text.rstrip()[:-1] + ', "zz_extra": NaN}')
    json.loads(snapshot.read_text())  # Python accepts NaN; only the digest rejects it.
    assert main(args) == 3
    assert calls == []
    assert not (tmp_path / "report.html").exists()


def test_worker_lifetime_without_signal_masks_still_resets_disposition(monkeypatch):
    calls = []
    monkeypatch.setattr(normalize.signal, "alarm", calls.append)
    monkeypatch.setattr(normalize.signal, "signal", lambda *args: calls.append(args))
    monkeypatch.delattr(normalize.signal, "pthread_sigmask", raising=False)
    with normalize.bounded_lifetime(5):
        pass
    assert calls == [(signal.SIGALRM, signal.SIG_DFL), 5, 0]
