import asyncio
import Codemp.bindings.codemp_client as libcodemp

class CodempClient():

	def __init__(self):
		self.handle = None
		self.id = None
		self.ready = False

	async def connect(self, server_host):
		self.handle = await libcodemp.connect(server_host)
		self.id = await self.handle.get_id()
		self.ready = True

	def disconnect(self):
		self.handle = None
		self.id = None
		self.ready = False
		# some code that tells the server to unsubscribe stuff as well.

	async def get_id(self):
		if self.ready and not self.id:
			self.id = await self.handle.get_id()
			return self.id
		elif self.ready:
			return self.id
		else:
			raise RuntimeError("Attemp to get id without an established connection.")

	async def create(self, path, content=None):
		if self.ready:
			return await self.handle.create(path, content)
		else:
			raise RuntimeError("Attemp to create a buffer without a connection.")

	async def listen(self):
		if self.ready:
			return CursorController(await self.handle.listen())
		else:
			raise RuntimeError("Attempt to listen without a connection.")

	async def attach(self, path):
		if self.ready:
			return ContentController(await self.handle.attach(path))
		else:
			raise RuntimeError("Attempt to attach without a connection.")

class CursorController():
	def __init__(self, handle):
		self.handle = handle

	async def send(self, path, start, end):
		await self.handle.send(path, start, end)

	def callback(self, coro, id):
		self.handle.callback(coro, id)

class ContentController():
	def __init__(self, handle):
		self.handle = handle

	def get_content(self):
		return self.handle.content()

	async def apply(self, skip, text, tail):
		return await self.handle.apply(skip, text, tail)

	def callback(self, coro, id):
		self.handle.callback(coro, id)

