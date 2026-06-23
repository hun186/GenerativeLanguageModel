class tqdm:
    _lock = None

    def __init__(self, iterable=None, total=None, desc=None, ncols=None, **kwargs):
        self.iterable = iterable
        self.total = total
        self.desc = desc
        self.n = 0

    def __iter__(self):
        if self.iterable is None:
            return iter(())
        return iter(self.iterable)

    def update(self, n=1):
        self.n += n

    def close(self):
        return None

    def set_description(self, *args, **kwargs):
        return None

    @classmethod
    def write(cls, s, file=None, **kwargs):
        print(s, file=file)

    @classmethod
    def set_lock(cls, lock):
        cls._lock = lock


def trange(*args, **kwargs):
    return tqdm(range(*args), **kwargs)
