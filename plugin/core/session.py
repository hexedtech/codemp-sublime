import logging
from ...lib import codemp

logger = logging.getLogger(__name__)

class SessionManager():
	def __init__(self) -> None:
		self._running = False
		self._driver = None
		self._client = None

	def is_init(self):
		return self._running and self._driver is not None

	def is_active(self):
		return self.is_init() and self._client is not None

	@property
	def client(self):
		return self._client

	def get_or_init(self) -> codemp.Driver:
		if self._driver:
			return self._driver

		self._driver = codemp.init()
		logger.debug("registering logger callback...")
		if not codemp.set_logger(lambda msg: logger.debug(msg), False):
			logger.debug(
				"could not register the logger... \
				If reconnecting it's ok, \
				the previous logger is still registered"
			)
		self._running = True
		return self._driver

	def stop(self):
		if not self._driver:
			return

		self.drop_client()
		self._driver.stop()
		self._running = False
		self._driver = None

	def connect(self, config: codemp.Config) -> codemp.Client:
		if not self.is_init():
			self.get_or_init()

		self._client = codemp.connect(config).wait()
		logger.debug(f"Connected to '{config.host}' as user {self._client.user_name} (id: {self._client.user_id})")
		return self._client

	def drop_client(self):
		self._client = None


session = SessionManager()