import asyncio
import Codemp.bindings.codemp_client as libcodemp

class CodempClient():

	def __init__(self):
		self.handle = libcodemp.codemp_init()

	async def connect(self, server_host): # -> None
		await self.handle.connect(server_host)

	def disconnect(self): # -> None
		self.handle = None

	async def create(self, path, content=None): # -> None
			await self.handle.create(path, content)
	
	# join a workspace
	async def join(self, session): # -> CursorController
			return CursorController(await self.handle.join(session))
		
	async def attach(self, path): # -> BufferController
			return BufferController(await self.handle.attach(path))
		
	async def get_cursor(self): # -> CursorController
			return CursorController(await self.handle.get_cursor())

	async def get_buffer(self, path): # -> BufferController
			return BufferController(await self.handle.get_buffer())

	async def disconnect_buffer(self, path): # -> None
			await self.handle.disconnect_buffer(path)

	async def leave_workspace(self): # -> None
		pass # todo 

class CursorController():
	def __init__(self, handle):
		self.handle = handle

	def send(self, path, start, end): # -> None
		self.handle.send(path, start, end)

	def try_recv(self): # -> Optional[CursorEvent]
		return self.handle.try_recv()

	async def recv(self): # -> CursorEvent
		return await self.handle.recv()

	async def poll(self): # -> None
		# await until new cursor event, then returns
		return await self.handle.poll()

	def drop_callback(self): # -> None
		self.handle.drop_callback()

	def callback(self, coro): # -> None
		self.handle.callback(coro)

class BufferController():
	def __init__(self, handle):
		self.handle = handle

	def get_content(self): # -> String
		return self.handle.content()

	def replace(self, txt): # -> None
		# replace the whole buffer.
		self.handle.replace(txt)

	def insert(self, txt, pos): # -> None
		# insert text at buffer position pos
		self.handle.insert(txt, pos)

	def delta(self, start, txt, end): # -> None
		# delta in the region start..end with txt new content
		self.handle.delta(start, txt, end)

	def delete(self, pos, count): # -> None
		# delete starting from pos, count chars.
		self.handle.delete(pos, count)

	def cancel(self, pos, count): # -> None
		# cancel backward `count` elements from pos.
		self.handle.cancle(pos, count)

	def try_recv(self): # -> Optional[TextChange]
		return self.handle.try_recv()

	async def recv(self): # -> TextChange 
		return await self.handle.recv()

	async def poll(self): # -> ??
		return await self.handle.poll()

	def drop_callback(self): # -> None
		self.handle.drop_callback()

	def callback(self, coro): # -> None
		self.handle.callback(coro)





