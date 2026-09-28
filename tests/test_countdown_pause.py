import io

import pytest

import utils.utilities as utilities


class NonInteractiveStdin:
    def isatty(self):
        return False

    def fileno(self):
        raise AssertionError("fileno must not be queried for non-TTY stdin")


class UnsupportedInteractiveStdin:
    def isatty(self):
        return True

    def fileno(self):
        raise io.UnsupportedOperation("redirected stdin is pseudofile")


@pytest.mark.parametrize("stdin", [None, NonInteractiveStdin(), UnsupportedInteractiveStdin()])
def test_countdown_pause_returns_immediately_for_non_selectable_stdin(monkeypatch, stdin):
    monkeypatch.setattr(utilities.sys, "stdin", stdin)
    monkeypatch.setattr(
        utilities.time,
        "sleep",
        lambda _seconds: pytest.fail("headless countdown must not sleep"),
    )

    utilities.countdown_pause(10)


def test_countdown_pause_zero_returns_before_stdin_or_sleep(monkeypatch):
    class ExplodingStdin:
        def isatty(self):
            raise AssertionError("zero-second countdown must not inspect stdin")

    monkeypatch.setattr(utilities.sys, "stdin", ExplodingStdin())
    monkeypatch.setattr(
        utilities.time,
        "sleep",
        lambda _seconds: pytest.fail("zero-second countdown must not sleep"),
    )

    utilities.countdown_pause(0)
