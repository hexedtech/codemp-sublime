from asyncio import CancelledError

from codemp import PyLogger
from Codemp.src.utils import status_log


class CodempLogger:
    def __init__(self, debug: bool = False):
        self.handle = None
        self.started = False
        try:
            self.handle = PyLogger(debug)
        except Exception:
            pass

    async def log(self):
        if self.started:
            return

        self.started = True
        status_log("spinning up the logger...")
        try:
            while msg := await self.handle.listen():
                print(msg)
        except CancelledError:
            status_log("stopping logger")
            self.started = False
            raise
        except Exception as e:
            status_log(f"logger crashed unexpectedly:\n{e}")
            raise


DEBUG = False
logger = CodempLogger(DEBUG)
