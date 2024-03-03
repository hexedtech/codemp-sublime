from typing import Optional
import asyncio
import Codemp.ext.sublime_asyncio as rt


class TaskManager:
    def __init__(self, exit_handler):
        self.tasks = []
        self.exit_handler_id = rt.acquire(exit_handler)

    def release(self, at_exit):
        rt.release(at_exit=at_exit, exit_handler_id=self.exit_handler_id)

    def dispatch(self, coro, name):
        rt.dispatch(coro, self.store_named_lambda(name))

    def sync(self, coro):
        rt.sync(coro)

    def remove_stopped(self):
        self.tasks = list(filter(lambda T: not T.cancelled(), self.tasks))

    def store(self, task, name=None):
        if name is not None:
            task.set_name(name)
        self.tasks.append(task)
        self.remove_stopped()

    def store_named_lambda(self, name):
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
            return self.task.pop(idx)
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
            rt.dispatch(self._stop(t))

    def stop_all(self):
        for task in self.tasks:
            rt.dispatch(self._stop(task))
