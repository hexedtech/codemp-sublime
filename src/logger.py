import logging
from asyncio import CancelledError
from codemp import PyLogger


class CodempLogger:
    def __init__(self, log_level):
        self.logger = logging.getLogger(__name__)
        self.level = log_level
        self.logger.setLevel(self.level)
        self.internal_logger = None
        self.started = False

        try:
            # PyLogger spins a tracing_subscriber rust side with a
            # .try_init() and errors out if already initialized.
            # initialize only once
            self.internal_logger = PyLogger(self.level == logging.DEBUG)
        except Exception:
            pass

    async def listen(self):
        if self.started:
            return
        self.started = True
        self.logger.debug("spinning up internal logger listener...")

        assert self.internal_logger is not None
        try:
            while msg := await self.internal_logger.listen():
                self.logger.log(self.level, msg)
        except CancelledError:
            self.logger.debug("inner logger stopped.")
            self.started = False
            raise
        except Exception as e:
            self.logger.error(f"inner logger crashed unexpectedly: \n {e}")
            raise e

    def log(self, msg):
        self.logger.log(self.level, msg)


inner_logger = CodempLogger(logging.INFO)
