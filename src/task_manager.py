from typing import Optional, Callable, Any
import sublime
import logging
import asyncio
import threading
import concurrent.futures

# from ..ext import sublime_asyncio as rt

logger = logging.getLogger(__name__)


class sublimeWorkerThreadExecutor(concurrent.futures.Executor):
    def __init__(self):
        self._futures_pending = 0
        self._shutting_down = False

        # reentrant lock: we either increment from the main thread (submit calls)
        # or we decrement from the worker thread (futures)
        self._condvar = threading.Condition()

    def submit(
        self, fn: Callable[..., Any], *args: Any, **kwargs: Any
    ) -> concurrent.futures.Future:
        if self._shutting_down:
            raise RuntimeError("Executor is shutting down")

        with self._condvar:
            self._futures_pending += 1

        logger.debug("Spawning a future in the main thread")
        future = concurrent.futures.Future()

        def coro() -> None:
            logger.debug("Running a future from the worker thread")
            try:
                future.set_result(fn(*args, **kwargs))
            except BaseException as e:
                future.set_exception(e)
            with self._condvar:
                self._futures_pending -= 1

        sublime.set_timeout_async(coro)
        return future

    def shutdown(self, wait: bool = True) -> None:
        self._shutting_down = True
        if not wait:
            return

        with self._condvar:
            self._condvar.wait_for(lambda: self._futures_pending == 0)


class Runtime:
    def __init__(self):
        self.tasks = []
        self.loop = asyncio.get_event_loop()
        self.loop.set_default_executor(sublimeWorkerThreadExecutor())
        self.loop.set_debug(True)

    def __del__(self):
        logger.debug("closing down the event loop")
        for task in self.tasks:
            task.cancel()

        try:
            self.loop.run_until_complete(self.loop.shutdown_asyncgens())
        except Exception as e:
            logger.error(f"Unexpected crash while shutting down event loop: {e}")

        self.loop.close()

    def start(self):
        pass

    def stop_loop(self):
        self.loop.call_soon_threadsafe(lambda: asyncio.get_running_loop().stop())

    def block_on(self, fut):
        return self.loop.run_until_complete(fut)

    def dispatch(self, coro, name=None):
        logging.debug("dispatching coroutine...")

        def make_task():
            logging.debug("creating task on the loop.")
            task = self.loop.create_task(coro)
            task.set_name(name)
            self.tasks.append(task)

        self.loop.call_soon_threadsafe(make_task)

    def get_task(self, name) -> Optional[asyncio.Task]:
        return next((t for t in self.tasks if t.get_name() == name), None)

    def stop_task(self, name):
        task = self.get_task(name)
        if task is not None:
            self.block_on(self.wait_for_cancel(task))

    async def wait_for_cancel(self, task):
        task.cancel()  # cancelling a task, merely requests a cancellation.
        try:
            await task
        except asyncio.CancelledError:
            return


# class TaskManager:
#     def __init__(self):
#         self.tasks = []
#         self.runtime = rt
#         self.exit_handler_id = None

#     def acquire(self, exit_handler):
#         if self.exit_handler_id is None:
#             # don't allow multiple exit handlers
#             self.exit_handler_id = self.runtime.acquire(exit_handler)

#         return self.exit_handler_id

#     def release(self, at_exit):
#         self.runtime.release(at_exit=at_exit, exit_handler_id=self.exit_handler_id)
#         self.exit_handler_id = None

#     def dispatch(self, coro, name=None):
#         self.runtime.dispatch(coro, self.store_named_lambda(name))

#     def sync(self, coro):
#         return self.runtime.sync(coro)

#     def remove_stopped(self):
#         self.tasks = list(filter(lambda T: not T.cancelled(), self.tasks))

#     def store(self, task, name=None):
#         if name is not None:
#             task.set_name(name)
#         self.tasks.append(task)
#         self.remove_stopped()

#     def store_named_lambda(self, name=None):
#         def _store(task):
#             self.store(task, name)

#         return _store

#     def get_task(self, name) -> Optional[asyncio.Task]:
#         return next((t for t in self.tasks if t.get_name() == name), None)

#     def get_task_idx(self, name) -> Optional[int]:
#         return next(
#             (i for (i, t) in enumerate(self.tasks) if t.get_name() == name), None
#         )

#     def pop_task(self, name) -> Optional[asyncio.Task]:
#         idx = self.get_task_idx(name)
#         if id is not None:
#             return self.tasks.pop(idx)
#         return None

#     async def _stop(self, task):
#         task.cancel()  # cancelling a task, merely requests a cancellation.
#         try:
#             await task
#         except asyncio.CancelledError:
#             return

#     def stop(self, name):
#         t = self.get_task(name)
#         if t is not None:
#             self.runtime.dispatch(self._stop(t))

#     def stop_all(self):
#         for task in self.tasks:
#             self.runtime.dispatch(self._stop(task))


# # singleton instance
# tm = TaskManager()

rt = Runtime()
