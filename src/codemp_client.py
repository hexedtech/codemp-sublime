import asyncio
import Codemp.bindings.codemp_client as libcodemp

# These are helper wrappers, not very interesting

class CodempClient():

	def __init__(self):
		self.handle = libcodemp.codemp_init()
## Bindings
	async def connect(self, server_host): # -> None
		await self.handle.connect(server_host)
	
	async def join(self, session): # -> CursorController
		return CursorController(await self.handle.join(session))

	async def create(self, path, content=None): # -> None
		await self.handle.create(path, content)
		
	async def attach(self, path): # -> BufferController
		return BufferController(await self.handle.attach(path))
		
	async def get_cursor(self): # -> CursorController
		return CursorController(await self.handle.get_cursor())

	async def get_buffer(self, path): # -> BufferController
		return BufferController(await self.handle.get_buffer())

	async def leave_workspace(self): # -> None
		await self.handle.leave_workspace()
	
	async def disconnect_buffer(self, path): # -> None
		await self.handle.disconnect_buffer(path)

	async def select_buffer(self): # -> String
		await self.handle.select_buffer()

class CursorController():
	def __init__(self, handle):
		self.handle = handle

	def send(self, buffer_id, start, end): # -> None
		self.handle.send(buffer_id, start, end)

	def try_recv(self): # -> Optional[CursorEvent]
		return self.handle.try_recv()

	async def recv(self): # -> CursorEvent
		return await self.handle.recv()

	async def poll(self): # -> None
		# await until new cursor event, then returns
		return await self.handle.poll()

class BufferController():
	def __init__(self, handle):
		self.handle = handle

	def content(self): # -> String
		return self.content()

	def send(self, start, end, txt): # -> None
		self.handle.send(start, end, txt)

	def try_recv(self): # -> Optional[TextChange]
		return self.handle.try_recv()

	async def recv(self): # -> TextChange 
		return await self.handle.recv()

	async def poll(self): # -> ??
		return await self.handle.poll()





