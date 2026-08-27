"""Small protocol fakes used by API unit tests."""


class ReadyDatabase:
    def __init__(self, *, ready: bool = True) -> None:
        self.ready = ready
        self.closed = False

    async def is_ready(self) -> bool:
        return self.ready

    async def close(self) -> None:
        self.closed = True
