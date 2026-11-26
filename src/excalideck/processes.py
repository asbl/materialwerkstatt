"""Optional process adapter for managed hosts; standalone generation uses subprocess."""
from contextlib import contextmanager
from contextvars import ContextVar
import subprocess

_runner = ContextVar("excalideck_process_runner", default=None)


@contextmanager
def process_scope(runner):
    token = _runner.set(runner)
    try:
        yield
    finally:
        _runner.reset(token)


def run_process(*args, **kwargs):
    runner = _runner.get()
    if runner is None:
        return subprocess.run(*args, **kwargs)
    # Pandoc JSON and SVG are data, not logs: preserve complete bounded output.
    return runner(*args, full_output=True, **kwargs)
