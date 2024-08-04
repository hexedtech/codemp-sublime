from typing import Optional
import asyncio
from ..ext import sublime_asyncio as rt


class TaskManager:
    def __init__(self):
        self.tasks = []
        self.runtime = rt
        self.exit_handler_id = None

    def acquire(self, exit_handler):
        if self.exit_handler_id is None:
            # don't allow multiple exit handlers
            self.exit_handler_id = self.runtime.acquire(exit_handler)

        return self.exit_handler_id

    def release(self, at_exit):
        self.runtime.release(at_exit=at_exit, exit_handler_id=self.exit_handler_id)

    def dispatch(self, coro, name=None):
        self.runtime.dispatch(coro, self.store_named_lambda(name))

    def sync(self, coro):
        self.runtime.sync(coro)

    def remove_stopped(self):
        self.tasks = list(filter(lambda T: not T.cancelled(), self.tasks))

    def store(self, task, name=None):
        if name is not None:
            task.set_name(name)
        self.tasks.append(task)
        self.remove_stopped()

    def store_named_lambda(self, name=None):
        def _store(task):
            self.store(task, name)

        return _store

    def get_task(self, name) -> Optional:
        return next((t for t in self.tasks if t.get_name() == name), None)

    def get_task_idx(self, name) -> Optional:
        return next(
            (i for (i, t) in enumerate(self.tasks) if t.get_name() == name), None
        )

    def pop_task(self, name) -> Optional:
        idx = self.get_task_idx(name)
        if id is not None:
            return self.tasks.pop(idx)
        return None

    async def _stop(self, task):
        task.cancel()  # cancelling a task, merely requests a cancellation.
        try:
            await task
        except asyncio.CancelledError:
            return

    def stop(self, name):
        t = self.get_task(name)
        if t is not None:
            self.runtime.dispatch(self._stop(t))

    def stop_all(self):
        for task in self.tasks:
            self.runtime.dispatch(self._stop(task))


# singleton instance
tm = TaskManager()
