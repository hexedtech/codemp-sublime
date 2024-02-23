from typing import Optional
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

    def store(self, task):
        self.tasks.append(task)

    def store_named(self, task, name=None):
        task.set_name(name)
        self.store(task)

    def store_named_lambda(self, name):
        def _store(task):
            task.set_name(name)
            self.store(task)

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

    def stop(self, name):
        t = self.get_task(name)
        if t is not None:
            t.cancel()

    def stop_and_pop(self, name) -> Optional:
        idx, task = next(
            ((i, t) for (i, t) in enumerate(self.tasks) if t.get_name() == name),
            (None, None),
        )
        if idx is not None:
            task.cancel()
            return self.tasks.pop(idx)

    def stop_all(self):
        for task in self.tasks:
            task.cancel()
