import logging
import codemp

from typing import Optional

from ..utils import some

logger = logging.getLogger(__name__)

class SessionManager():
	def __init__(self) -> None:
		self._running = False
		self._driver = None
		self._client = None
		self._config: codemp.Config | None = None

	def is_init(self):
		return self._running and self._driver is not None

	def is_active(self):
		return self.is_init() and self._client is not None

	@property
	def client(self):
		return some(self._client)

	@property
	def config(self):
		return some(self._config)

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

	def connect(self, config: Optional[codemp.Config] = None) -> codemp.Client:
		if not self.is_init():
			self.get_or_init()

		if config:
			self._config = config

		self._client = codemp.connect(self.config).wait()

		logger.debug(f"Connected to '{self.config.host}' as user {self._client.current_user().name} (id: {self._client.current_user().id})")
		return self._client

	def get_workspaces(self, owned: bool = True, invited: bool = True):
		owned_wss = self.client.fetch_owned_workspaces().wait() if owned else []
		invited_wss = self.client.fetch_joined_workspaces().wait() if invited else []

		return owned_wss + invited_wss

	def drop_client(self):
		self._client = None

session = SessionManager()