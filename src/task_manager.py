from typing import Optional, Callable, Any

import sublime
import logging
import asyncio
import threading
import concurrent.futures

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
        self.loop = asyncio.new_event_loop()
        self.loop.set_default_executor(sublimeWorkerThreadExecutor())
        self.loop.set_debug(True)
        self.thread = threading.Thread(
            target=self.loop.run_forever, name="codemp-asyncio-loop"
        )
        logger.debug("spinning up even loop in its own thread.")
        self.thread.start()

    def __del__(self):
        logger.debug("closing down the event loop.")
        for task in asyncio.all_tasks(self.loop):
            task.cancel()

        self.stop_loop()

        try:
            self.loop.run_until_complete(self.loop.shutdown_asyncgens())
        except Exception as e:
            logger.error(f"Unexpected crash while shutting down event loop: {e}")

        self.thread.join()

    def stop_loop(self):
        logger.debug("stopping event loop.")
        self.loop.call_soon_threadsafe(lambda: asyncio.get_running_loop().stop())

    def run_blocking(self, fut, *args, **kwargs):
        return self.loop.run_in_executor(None, fut, *args, **kwargs)

    def dispatch(self, coro, name=None):
        """
        Dispatch a task on the event loop and returns the task itself.
        Similar to `run_coroutine_threadsafe` but returns the
        actual task running and not the result of the coroutine.

        `run_coroutine_threadsafe` returns a concurrent.futures.Future
        which has a blocking .result so not really suited for long running
        coroutines
        """
        logger.debug("dispatching coroutine...")

        def make_task(fut):
            logger.debug("creating task on the loop.")
            try:
                fut.set_result(self.loop.create_task(coro))
            except Exception as e:
                fut.set_exception(e)

        # create the future to populate with the task
        # we use the concurrent.futures.Future since it is thread safe
        # and the .result() call is blocking.
        fut = concurrent.futures.Future()
        self.loop.call_soon_threadsafe(make_task, fut)
        task = fut.result(None)  # wait for the task to be created
        task.set_name(name)
        self.tasks.append(task)  # save the reference
        return task

    def block_on(self, coro, timeout=None):
        fut = asyncio.run_coroutine_threadsafe(coro, self.loop)
        try:
            return fut.result(timeout)
        except asyncio.CancelledError:
            logger.debug("future got cancelled.")
            raise
        except TimeoutError:
            logger.debug("future took too long to finish.")
            raise
        except Exception as e:
            raise e

    def get_task(self, name) -> Optional[asyncio.Task]:
        return next((t for t in self.tasks if t.get_name() == name), None)

    def stop_task(self, name):
        task = self.get_task(name)
        if task is not None:
            self.dispatch(self.wait_for_cancel(task))

    async def wait_for_cancel(self, task):
        task.cancel()  # cancelling a task, merely requests a cancellation.
        try:
            await task
        except asyncio.CancelledError:
            return


# store a global in the module so it acts as a singleton
# (modules are loaded only once)
# rt = Runtime()
