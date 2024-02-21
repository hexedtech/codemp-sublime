from __future__ import annotations
from typing import Optional, Callable

import sublime
import sublime_plugin

import Codemp.ext.sublime_asyncio as sublime_asyncio

import asyncio  # noqa: F401
import typing  # noqa: F401
import tempfile
import os
from Codemp.bindings.codemp_client import codemp_init, PyCursorEvent, PyTextChange, PyId

# Some utility functions


def status_log(msg):
    sublime.status_message("[codemp] {}".format(msg))
    print("[codemp] {}".format(msg))


def rowcol_to_region(view, start, end):
    a = view.text_point(start[0], start[1])
    b = view.text_point(end[0], end[1])
    return sublime.Region(a, b)


def is_active(view):
    if view.window().active_view() == view:
        return True
    return False


def safe_listener_detach(txt_listener):
    if txt_listener.is_attached():
        txt_listener.detach()


###############################################################################


# This class is used as an abstraction between the local buffers (sublime side) and the
# remote buffers (codemp side), to handle the syncronicity.
# This class is mainly manipulated by a VirtualWorkspace, that manages its buffers
# using this abstract class
class VirtualBuffer:
    def __init__(
        self,
        view: sublime.View,
        remote_id: str,
        workspace: VirtualWorkspace,
        buffctl: BufferController,
    ):
        self.view = view
        self.codemp_id = remote_id
        self.sublime_id = view.buffer_id()
        self.worker_task_name = "buffer-worker-{}".format(self.codemp_id)

        self.workspace = workspace
        self.buffctl = buffctl

        self.tmpfile = os.path.join(workspace.rootdir, self.codemp_id)

        self.view.set_name(self.codemp_id)
        open(self.tmpfile, "a").close()
        self.view.retarget(self.tmpfile)
        self.view.set_scratch(True)

        # mark the view as a codemp view
        self.view.set_status("z_codemp_buffer", "[Codemp]")
        self.view.settings()["codemp_buffer"] = True

        # # start the buffer worker that waits for text_changes in the worker thread
        # sublime_asyncio.dispatch(
        #     self.apply_buffer_change_task(), store_task(self.worker_task_name)
        # )

    def cleanup(self):
        os.remove(self.tmpfile)
        # cleanup views
        del self.view.settings()["codemp_buffer"]
        self.view.erase_status("z_codemp_buffer")
        self.view.erase_regions("codemp_cursors")

        # the text listener should be detached by the event listener
        # on close and on_deactivated events.


# A virtual workspace is a bridge class that aims to translate
# events that happen to the codemp workspaces into sublime actions


class VirtualWorkspace:
    def __init__(self, client: VirtualClient, workspace_id: str, handle: Workspace):
        self.id = workspace_id
        self.sublime_window = sublime.active_window()
        self.client = client
        self.handle = handle
        self.curctl = handle.cursor()

        self.active_buffers: list[VirtualBuffer] = []

        # REMEMBER TO DELETE THE TEMP STUFF!
        # initialise the virtual filesystem
        tmpdir = tempfile.mkdtemp(prefix="codemp_")
        status_log("setting up virtual fs for workspace in: {} ".format(tmpdir))
        self.rootdir = tmpdir

        # and add a new "project folder"
        proj_data = self.sublime_window.project_data()
        if proj_data is None:
            proj_data = {"folders": []}
        proj_data["folders"].append(
            {"name": "CODEMP::" + workspace_id, "path": self.rootdir}
        )
        self.sublime_window.set_project_data(proj_data)

        # start the event listener?

    def cleanup(self):
        # the worskpace only cares about closing the various open views on its buffers.
        # the event listener calls the cleanup code for each buffer independently on its own.
        for vbuff in self.active_buffers:
            vbuff.view.close()

        d = self.sublime_window.project_data()
        newf = filter(lambda F: not F["name"].startwith("CODEMP::"), d["folders"])
        d["folders"] = newf
        self.sublime_window.set_project_data(d)

        os.removedirs(self.rootdir)

    def get_virtual_by_local(self, id: str) -> Optional[VirtualBuffer]:
        return next(
            (vbuff for vbuff in self.active_buffers if vbuff.sublime_id == id), None
        )

    def get_virtual_by_remote(self, id: str) -> Optional[VirtualBuffer]:
        return next(
            (vbuff for vbuff in self.active_buffers if vbuff.codemp_id == id), None
        )

    async def attach(self, id: str):
        if id is None:
            status_log("can't attach if buffer does not exist, aborting.")
            return

        await self.handle.fetch_buffers()
        existing_buffers = self.handle.filetree()
        if id not in existing_buffers:
            try:
                await self.handle.create(id)
            except Exception as e:
                status_log(f"could not create buffer: {e}")
                return

        try:
            buff_ctl = await self.handle.attach(id)
        except Exception as e:
            status_log(f"error when attaching to buffer '{id}': {e}")
            return

        # REMEMBER TO DEAL WITH DELETING THESE THINGS!
        view = self.sublime_window.new_file()
        vbuff = VirtualBuffer(view, id, self, buff_ctl)
        self.active_buffers.append(vbuff)

        self.client.spawn_buffer_manager(vbuff)

        # if the view is already active calling focus_view() will not trigger the on_activate()
        self.sublime_window.focus_view(view)


class VirtualClient:
    def __init__(self, on_exit: Callable = None):
        self.handle: Client = Client()
        self.workspaces: list[VirtualWorkspace] = []
        self.active_workspace: VirtualWorkspace = None
        self.tm = TaskManager(on_exit)

        self.change_clock = 0

    def make_active(self, ws: VirtualWorkspace):
        # TODO: Logic to deal with swapping to and from workspaces,
        # what happens to the cursor tasks etc..
        if self.active_workspace is not None:
            self.tm.stop_and_pop(f"move-cursor-{self.active_workspace.id}")
        self.active_workspace = ws
        self.spawn_cursor_manager(ws)

    def get_virtual_local(self, id: str) -> Optional[VirtualWorkspace]:
        # get's the workspace that contains a buffer
        next(
            (
                vws
                for vws in self.workspaces
                if vws.get_virtual_by_local(id) is not None
            ),
            None,
        )

    def get_virtual_remote(self, id: str) -> Optional[VirtualWorkspace]:
        # get's the workspace that contains a buffer
        next(
            (
                vws
                for vws in self.workspaces
                if vws.get_virtual_by_remote(id) is not None
            ),
            None,
        )

    async def connect(self, server_host: str):
        status_log(f"Connecting to {server_host}")
        try:
            await self.handle.connect(server_host)
        except Exception:
            sublime.error_message("Could not connect:\n Make sure the server is up.")
            return

        id = await self.handle.user_id()
        print(f"TEST: {id}")

    async def join_workspace(
        self, workspace_id: str, user="sublime", password="lmaodefaultpassword"
    ):
        try:
            status_log(f"Logging into workspace: '{workspace_id}'")
            await self.handle.login(user, password, workspace_id)
        except Exception as e:
            sublime.error_message(f"Failed to login to workspace '{workspace_id}': {e}")
            return

        try:
            status_log(f"Joining workspace: '{workspace_id}'")
            workspace_handle = await self.handle.join_workspace(workspace_id)
        except Exception as e:
            sublime.error_message(f"Could not join workspace '{workspace_id}': {e}")
            return

        print(workspace_handle.id())

        # here we should also start the workspace event watcher task
        vws = VirtualWorkspace(self, workspace_id, workspace_handle)
        self.make_active(vws)
        self.workspaces.append(vws)

    def spawn_cursor_manager(self, virtual_workspace: VirtualWorkspace):
        async def move_cursor_task(vws):
            global _regions_colors
            global _palette

            status_log(f"spinning up cursor worker for workspace '{vws.id}'...")
            # TODO: make the matching user/color more solid. now all users have one color cursor.
            # Maybe make all cursors the same color and only use annotations as a discriminant.
            # idea: use a user id hash map that maps to a color.
            try:
                while cursor_event := await vws.curctl.recv():
                    vbuff = vws.get_virtual_by_remote(cursor_event.buffer)

                    if vbuff is None:
                        status_log(
                            f"Received a cursor event for an unknown or inactive buffer: {cursor_event.buffer}"
                        )
                        continue

                    reg = rowcol_to_region(
                        vbuff.view, cursor_event.start, cursor_event.end
                    )
                    reg_flags = sublime.RegionFlags.DRAW_EMPTY  # show cursors.

                    user_hash = hash(cursor_event.user)

                    vbuff.view.add_regions(
                        f"codemp-cursors-{user_hash}",
                        [reg],
                        flags=reg_flags,
                        scope=_regions_colors[user_hash % len(_regions_colors)],
                        annotations=[cursor_event.user],
                        annotation_color=_palette[user_hash % len(_palette)],
                    )

            except asyncio.CancelledError:
                status_log(f"cursor worker for '{vws.id}' stopped...")
                return

        self.tm.dispatch(
            move_cursor_task(virtual_workspace), f"cursor-ctl-{virtual_workspace.id}"
        )

    def send_cursor(self, vbuff: VirtualBuffer):
        # TODO: only the last placed cursor/selection.
        status_log(f"sending cursor position in workspace: {vbuff.workspace.id}")
        region = vbuff.view.sel()[0]
        start = vbuff.view.rowcol(region.begin())  # only counts UTF8 chars
        end = vbuff.view.rowcol(region.end())

        vbuff.workspace.curctl.send(vbuff.codemp_id, start, end)

    def spawn_buffer_manager(self, vbuff: VirtualBuffer):
        status_log("spawning buffer manager")

        async def apply_buffer_change_task(vb):
            status_log(f"spinning up '{vb.codemp_id}' buffer worker...")
            try:
                while text_change := await vb.buffctl.recv():
                    # In case a change arrives to a background buffer, just apply it.
                    # We are not listening on it. Otherwise, interrupt the listening
                    # to avoid echoing back the change just received.
                    if text_change.is_empty():
                        status_log("change is empty. skipping.")
                        continue

                    vb.view.settings()[
                        "codemp_ignore_next_on_modified_text_event"
                    ] = True

                    # we need to go through a sublime text command, since the method,
                    # view.replace needs an edit token, that is obtained only when calling
                    # a textcommand associated with a view.
                    vb.view.run_command(
                        "codemp_replace_text",
                        {
                            "start": text_change.start_incl,
                            "end": text_change.end_excl,
                            "content": text_change.content,
                            "change_id": vb.view.change_id(),
                        },
                    )

            except asyncio.CancelledError:
                status_log("'{}' buffer worker stopped...".format(vb.codemp_id))

        self.tm.dispatch(
            apply_buffer_change_task(vbuff), f"buffer-ctl-{vbuff.codemp_id}"
        )

    def send_buffer_change(self, changes, vbuff: VirtualBuffer):
        # we do not do any index checking, and trust sublime with providing the correct
        # sequential indexing, assuming the changes are applied in the order they are received.
        for change in changes:
            region = sublime.Region(change.a.pt, change.b.pt)
            status_log(
                "sending txt change: Reg({} {}) -> '{}'".format(
                    region.begin(), region.end(), change.str
                )
            )
            vbuff.buffctl.send(region.begin(), region.end(), change.str)


class TaskManager:
    def __init__(self, exit_handler):
        self.tasks = []
        self.exit_handler_id = sublime_asyncio.acquire(exit_handler)

    def release(self, at_exit):
        sublime_asyncio.release(at_exit, self.exit_handler_id)

    def dispatch(self, coro, name):
        sublime_asyncio.dispatch(coro, self.store_named_lambda(name))

    def sync(self, coro):
        sublime_asyncio.sync(coro)

    def store(self, task):
        self.tasks.append(task)

    def store_named(self, task, name=None):
        task.set_name(name)
        self.store(task)

    def store_named_lambda(self, name):
        def _store(task):
            task.set_name(name)
            self.store(task)

        return _store

    def get_task(self, name) -> Optional:
        return next((t for t in self.tasks if t.get_name() == name), None)

    def get_task_idx(self, name) -> Optional:
        return next(
            (i for (i, t) in enumerate(self.tasks) if t.get_name() == name), None
        )

    def pop_task(self, name) -> Optional:
        idx = self.get_task_idx(name)
        if id is not None:
            return self.task.pop(idx)
        return None

    def stop(self, name):
        t = self.get_task(name)
        if t is not None:
            t.cancel()

    def stop_and_pop(self, name) -> Optional:
        idx, task = next(
            ((i, t) for (i, t) in enumerate(self.tasks) if t.get_name() == name),
            (None, None),
        )
        if idx is not None:
            task.cancel()
            return self.tasks.pop(idx)

    def stop_all(self):
        for task in self.tasks:
            task.cancel()

######################################################################################
# These are helper wrappers, that wrap the coroutines returned from the
# pyo3 bindings into usable awaitable functions.
# These should not be directly extended but rather use the higher level "virtual" counterparts above.

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
        # await until new cursor event, then returns
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
