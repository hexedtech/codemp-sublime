from __future__ import annotations
from typing import Optional
from ..bindings.codemp import codemp_init, PyCursorEvent, PyTextChange, PyId

######################################################################################
# These are helper wrappers, that wrap the coroutines returned from the
# pyo3 bindings into usable awaitable functions.
# These should not be directly extended but rather use the higher
# level "virtual" counterparts above.

# All methods, without an explicit 'noexcept' are to be treated as failable
# and can throw an error


class CursorController:
    def __init__(self, handle) -> None:  # noexcept
        self.handle = handle

    def send(self, path: str, start: tuple[int, int], end: tuple[int, int]) -> None:
        self.handle.send(path, start, end)

    def try_recv(self) -> Optional[PyCursorEvent]:
        return self.handle.try_recv()

    async def recv(self) -> PyCursorEvent:
        return await self.handle.recv()

    async def poll(self) -> None:
        return await self.handle.poll()


class BufferController:
    def __init__(self, handle) -> None:  # noexcept
        self.handle = handle

    def send(self, start: int, end: int, txt: str) -> None:
        self.handle.send(start, end, txt)

    def try_recv(self) -> Optional[PyTextChange]:
        return self.handle.try_recv()

    async def recv(self) -> PyTextChange:
        return await self.handle.recv()

    async def poll(self) -> None:
        return await self.handle.poll()


class Workspace:
    def __init__(self, handle) -> None:  # noexcept
        self.handle = handle

    async def create(self, path: str) -> None:
        await self.handle.create(path)

    async def attach(self, path: str) -> BufferController:
        return BufferController(await self.handle.attach(path))

    async def fetch_buffers(self) -> None:
        await self.handle.fetch_buffers()

    async def fetch_users(self) -> None:
        await self.handle.fetch_users()

    async def list_buffer_users(self, path: str) -> list[PyId]:
        return await self.handle.list_buffer_users(path)

    async def delete(self, path) -> None:
        await self.handle.delete(path)

    def id(self) -> str:  # noexcept
        return self.handle.id()

    def cursor(self) -> CursorController:
        return CursorController(self.handle.cursor())

    def buffer_by_name(self, path) -> BufferController:
        return BufferController(self.handle.buffer_by_name(path))

    def filetree(self) -> list[str]:  # noexcept
        return self.handle.filetree()


class Client:
    def __init__(self) -> None:
        self.handle = codemp_init()

    async def connect(self, server_host: str) -> None:
        await self.handle.connect(server_host)

    async def login(self, user: str, password: str, workspace: Optional[str]) -> None:
        await self.handle.login(user, password, workspace)

    async def join_workspace(self, workspace: str) -> Workspace:
        return Workspace(await self.handle.join_workspace(workspace))

    async def get_workspace(self, id: str) -> Optional[Workspace]:
        return Workspace(await self.handle.get_workspace(id))

    async def user_id(self) -> str:
        return await self.handle.user_id()
