from contextlib import contextmanager

@contextmanager
def logging_redirect_tqdm(*args, **kwargs):
    yield
