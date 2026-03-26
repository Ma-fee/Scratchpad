import asyncio
import os
from typing import Optional


class AsyncExecutor:
    def __init__(self, max_concurrent: Optional[int] = None):
        if max_concurrent is not None:
            if not isinstance(max_concurrent, int):
                raise TypeError("max_concurrent must type int")
            if max_concurrent < 0:
                raise ValueError("max_concurrent must be greater than 0")
        self._max_concurrent = max_concurrent or os.cpu_count()
        self.sem = asyncio.Semaphore(self._max_concurrent)
        self._queued = []
        self._pending = set()
        self._completed = set()

    def submit(self, func, *args, **kwargs):
        task = asyncio.create_task(self._wrap(self.sem, func, args, kwargs))
        self._queued.append(task)
        return task

    @staticmethod
    async def _wrap(event, func, args, kwargs):
        async with event:
            return await func(*args, **kwargs)

    # def _fill(self):
    #     for _ in range(self._max_concurrent - len(self._pending)):
    #         if not self._queued:
    #             return
    #         event, task = self._queued.pop(0)
    #         event.set()
    #         self._pending.add(task)

    def __len__(self):
        return len(self._queued) + len(self._pending) + len(self._completed)

    def __aiter__(self):
        return self

    async def wait(self):
        return await asyncio.gather(*self._queued, return_exceptions=True)

    async def __anext__(self):
        if not len(self):
            raise StopAsyncIteration

        if not self._completed:
            self._fill()
            self._completed, self._pending = await asyncio.wait(
                self._pending, return_when=asyncio.FIRST_COMPLETED
            )

        return self._completed.pop()
