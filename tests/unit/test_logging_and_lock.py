import logging

import pytest

from carl.lockfile import InstanceLock, LockHeldError
from carl.logging_setup import KeyValueFormatter, RedactingFilter, mask
from tests.conftest import TOKEN


def _record(msg, *args):
    return logging.LogRecord("carl.test", logging.INFO, __file__, 1, msg, args, None)


def test_mask_removes_discord_token():
    assert TOKEN not in mask(f"login with {TOKEN} failed")
    assert "[REDACTED_TOKEN]" in mask(f"login with {TOKEN} failed")


def test_mask_removes_healthcheck_path():
    out = mask("GET https://hc-ping.com/0a1b2c3d-secret failed")
    assert "0a1b2c3d" not in out
    assert out.startswith("GET https://hc-ping.com/")


def test_filter_masks_formatted_arguments():
    record = _record("token is %s", TOKEN)
    assert RedactingFilter().filter(record)
    assert TOKEN not in KeyValueFormatter().format(record)


def test_voice_warnings_are_dropped_but_other_warnings_are_kept():
    from carl.logging_setup import DropVoiceNoise

    f = DropVoiceNoise()
    assert not f.filter(_record("PyNaCl is not installed, voice will NOT be supported"))
    assert f.filter(_record("something else happened"))


def test_formatter_layout():
    line = KeyValueFormatter().format(_record("event=ready"))
    ts, level, name, rest = line.split(" ", 3)
    assert ts.endswith("Z") and "T" in ts
    assert (level, name, rest) == ("INFO", "carl.test", "event=ready")


def test_second_lock_acquisition_fails(tmp_path):
    first = InstanceLock(tmp_path / "carl.lock")
    first.acquire()
    try:
        with pytest.raises(LockHeldError):
            InstanceLock(tmp_path / "carl.lock").acquire()
    finally:
        first.release()


def test_lock_can_be_reacquired_after_release(tmp_path):
    with InstanceLock(tmp_path / "carl.lock"):
        pass
    with InstanceLock(tmp_path / "carl.lock"):
        pass


def test_aiosqlite_never_logs_sql_values_even_at_debug():
    from carl.logging_setup import quiet_noisy_loggers

    logging.getLogger("aiosqlite").setLevel(logging.DEBUG)
    quiet_noisy_loggers("DEBUG")
    assert logging.getLogger("aiosqlite").level == logging.WARNING
    assert not logging.getLogger("aiosqlite").isEnabledFor(logging.DEBUG)
