from __future__ import annotations
from typing import Optional

import sublime
import random
import asyncio
import tempfile
import os
import shutil

from codemp import (
    init_logger,
    codemp_init,
    CodempBufferController,
    CodempWorkspace,
    Client,
)
from ..src import globals as g
from ..src.TaskManager import tm
from ..src.utils import status_log, rowcol_to_region


class CodempLogger:
    def __init__(self, debug: bool = False):
        self.handle = init_logger(debug)

    async def log(self):
        status_log("spinning up the logger...")
        try:
            while msg := await self.handle.message():
                print(msg)
        except asyncio.CancelledError:
            status_log("stopping logger")
            raise
        except Exception as e:
            status_log(f"logger crashed unexpectedly:\n{e}")
            raise


# This class is used as an abstraction between the local buffers (sublime side) and the
# remote buffers (codemp side), to handle the syncronicity.
# This class is mainly manipulated by a VirtualWorkspace, that manages its buffers
# using this abstract class
class VirtualBuffer:
    def __init__(
        self,
        workspace: VirtualWorkspace,
        remote_id: str,
        buffctl: CodempBufferController,
    ):
        self.view = sublime.active_window().new_file()
        self.codemp_id = remote_id
        self.sublime_id = self.view.buffer_id()

        self.workspace = workspace
        self.buffctl = buffctl

        self.tmpfile = os.path.join(workspace.rootdir, self.codemp_id)

        self.view.set_name(self.codemp_id)
        open(self.tmpfile, "a").close()
        self.view.retarget(self.tmpfile)
        self.view.set_scratch(True)

        tm.dispatch(
            self.apply_bufferchange_task(),
            f"{g.BUFFCTL_TASK_PREFIX}-{self.codemp_id}",
        )

        # mark the view as a codemp view
        s = self.view.settings()
        self.view.set_status(g.SUBLIME_STATUS_ID, "[Codemp]")
        s[g.CODEMP_BUFFER_TAG] = True
        s[g.CODEMP_REMOTE_ID] = self.codemp_id
        s[g.CODEMP_WORKSPACE_ID] = self.workspace.id

    def cleanup(self):
        os.remove(self.tmpfile)
        # cleanup views
        s = self.view.settings()
        del s[g.CODEMP_BUFFER_TAG]
        del s[g.CODEMP_REMOTE_ID]
        del s[g.CODEMP_WORKSPACE_ID]
        self.view.erase_status(g.SUBLIME_STATUS_ID)

        tm.stop(f"{g.BUFFCTL_TASK_PREFIX}-{self.codemp_id}")
        status_log(f"cleaning up virtual buffer '{self.codemp_id}'")

    async def apply_bufferchange_task(self):
        status_log(f"spinning up '{self.codemp_id}' buffer worker...")
        try:
            while text_change := await self.buffctl.recv():
                if text_change.is_empty():
                    status_log("change is empty. skipping.")
                    continue
                # In case a change arrives to a background buffer, just apply it.
                # We are not listening on it. Otherwise, interrupt the listening
                # to avoid echoing back the change just received.
                if self.view.id() == g.ACTIVE_CODEMP_VIEW:
                    self.view.settings()[g.CODEMP_IGNORE_NEXT_TEXT_CHANGE] = True

                # we need to go through a sublime text command, since the method,
                # view.replace needs an edit token, that is obtained only when calling
                # a textcommand associated with a view.
                self.view.run_command(
                    "codemp_replace_text",
                    {
                        "start": text_change.start_incl,
                        "end": text_change.end_excl,
                        "content": text_change.content,
                        "change_id": self.view.change_id(),
                    },  # pyright: ignore
                )

        except asyncio.CancelledError:
            status_log(f"'{self.codemp_id}' buffer worker stopped...")
            raise
        except Exception as e:
            status_log(f"buffer worker '{self.codemp_id}' crashed:\n{e}")
            raise

    def send_buffer_change(self, changes):
        # we do not do any index checking, and trust sublime with providing the correct
        # sequential indexing, assuming the changes are applied in the order they are received.
        for change in changes:
            region = sublime.Region(change.a.pt, change.b.pt)
            status_log(
                "sending txt change: Reg({} {}) -> '{}'".format(
                    region.begin(), region.end(), change.str
                )
            )
            self.buffctl.send(
                region.begin(), region.end() + len(change.str) - 1, change.str
            )

    def send_cursor(self, vws: VirtualWorkspace):
        # TODO: only the last placed cursor/selection.
        # status_log(f"sending cursor position in workspace: {vbuff.workspace.id}")
        region = self.view.sel()[0]
        start = self.view.rowcol(region.begin())  # only counts UTF8 chars
        end = self.view.rowcol(region.end())

        vws.curctl.send(self.codemp_id, start, end)


# A virtual workspace is a bridge class that aims to translate
# events that happen to the codemp workspaces into sublime actions
class VirtualWorkspace:
    def __init__(self, workspace_id: str, handle: CodempWorkspace):
        self.id = workspace_id
        self.sublime_window = sublime.active_window()
        self.handle = handle
        self.curctl = handle.cursor()
        self.isactive = False

        # mapping remote ids -> local ids
        self.id_map: dict[str, int] = {}
        self.active_buffers: dict[int, VirtualBuffer] = {}  # local_id -> VBuff

        # initialise the virtual filesystem
        tmpdir = tempfile.mkdtemp(prefix="codemp_")
        status_log("setting up virtual fs for workspace in: {} ".format(tmpdir))
        self.rootdir = tmpdir

        # and add a new "project folder"
        proj_data: dict = self.sublime_window.project_data()  # pyright: ignore
        if proj_data is None:
            proj_data = {"folders": []}

        proj_data["folders"].append(
            {"name": f"{g.WORKSPACE_FOLDER_PREFIX}{self.id}", "path": self.rootdir}
        )
        self.sublime_window.set_project_data(proj_data)

        s: dict = self.sublime_window.settings()  # pyright: ignore
        if s.get(g.CODEMP_WINDOW_TAG, False):
            s[g.CODEMP_WINDOW_WORKSPACES].append(self.id)
        else:
            s[g.CODEMP_WINDOW_TAG] = True
            s[g.CODEMP_WINDOW_WORKSPACES] = [self.id]

    def cleanup(self):
        self.deactivate()

        # the worskpace only cares about closing the various open views on its buffers.
        # the event listener calls the cleanup code for each buffer independently on its own.
        for vbuff in self.active_buffers.values():
            vbuff.view.close()

        self.active_buffers = {}  # drop all buffers, let them be garbace collected (hopefully)

        d: dict = self.sublime_window.project_data()  # pyright: ignore
        newf = list(
            filter(
                lambda f: f.get("name", "") != f"{g.WORKSPACE_FOLDER_PREFIX}{self.id}",
                d["folders"],
            )
        )
        d["folders"] = newf
        self.sublime_window.set_project_data(d)
        status_log(f"cleaning up virtual workspace '{self.id}'")
        shutil.rmtree(self.rootdir, ignore_errors=True)

        s = self.sublime_window.settings()
        del s[g.CODEMP_WINDOW_TAG]
        del s[g.CODEMP_WINDOW_WORKSPACES]

    def activate(self):
        tm.dispatch(
            self.move_cursor_task(),
            f"{g.CURCTL_TASK_PREFIX}-{self.id}",
        )
        self.isactive = True

    def deactivate(self):
        if self.isactive:
            tm.stop(f"{g.CURCTL_TASK_PREFIX}-{self.id}")
        self.isactive = False

    def add_buffer(self, remote_id: str, vbuff: VirtualBuffer):
        self.id_map[remote_id] = vbuff.view.buffer_id()
        self.active_buffers[vbuff.view.buffer_id()] = vbuff

    def get_by_local(self, local_id: int) -> Optional[VirtualBuffer]:
        return self.active_buffers.get(local_id)

    def get_by_remote(self, remote_id: str) -> Optional[VirtualBuffer]:
        local_id = self.id_map.get(remote_id)
        if local_id is None:
            return

        vbuff = self.active_buffers.get(local_id)
        if vbuff is None:
            status_log(
                "[WARN] a local-remote buffer id pair was found but not the matching virtual buffer."
            )
            return

        return vbuff

    async def attach(self, id: str):
        if id is None:
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

        vbuff = VirtualBuffer(self, id, buff_ctl)
        self.add_buffer(id, vbuff)

        # TODO! if the view is already active calling focus_view() will not trigger the on_activate
        self.sublime_window.focus_view(vbuff.view)

    async def move_cursor_task(self):
        status_log(f"spinning up cursor worker for workspace '{self.id}'...")
        try:
            while cursor_event := await self.curctl.recv():
                vbuff = self.get_by_remote(cursor_event.buffer)

                if vbuff is None:
                    continue

                reg = rowcol_to_region(vbuff.view, cursor_event.start, cursor_event.end)
                reg_flags = sublime.RegionFlags.DRAW_EMPTY  # show cursors.

                user_hash = hash(cursor_event.user)
                vbuff.view.add_regions(
                    f"{g.SUBLIME_REGIONS_PREFIX}-{user_hash}",
                    [reg],
                    flags=reg_flags,
                    scope=g.REGIONS_COLORS[user_hash % len(g.REGIONS_COLORS)],
                    annotations=[cursor_event.user],
                    annotation_color=g.PALETTE[user_hash % len(g.PALETTE)],
                )

        except asyncio.CancelledError:
            status_log(f"cursor worker for '{self.id}' stopped...")
            raise
        except Exception as e:
            status_log(f"cursor worker '{self.id}' crashed:\n{e}")
            raise


class VirtualClient:
    def __init__(self):
        self.handle: Client = codemp_init()
        self.workspaces: dict[str, VirtualWorkspace] = {}
        self.active_workspace: Optional[VirtualWorkspace] = None

    def __getitem__(self, key: str):
        return self.workspaces.get(key)

    def get_workspace(self, view):
        tag_id = view.settings().get(g.CODEMP_WORKSPACE_ID)
        if tag_id is None:
            return

        ws = self.workspaces.get(tag_id)
        if ws is None:
            status_log(
                "[WARN] a tag on the view was found but not a matching workspace."
            )
            return

        return ws

    def get_buffer(self, view):
        ws = self.get_workspace(view)
        return None if ws is None else ws.get_by_local(view.buffer_id())

    def make_active(self, ws: VirtualWorkspace | None):
        if self.active_workspace == ws:
            return

        if self.active_workspace is not None:
            self.active_workspace.deactivate()

        if ws is not None:
            ws.activate()

        self.active_workspace = ws

    async def connect(self, server_host: str):
        status_log(f"Connecting to {server_host}")
        try:
            await self.handle.connect(server_host)
        except Exception as e:
            sublime.error_message(
                f"Could not connect:\n Make sure the server is up.\nerror: {e}"
            )
            return

        id = await self.handle.user_id()
        status_log(f"Connected to '{server_host}' with user id: {id}")

    async def join_workspace(
        self,
        workspace_id: str,
        user=f"user-{random.random()}",
        password="lmaodefaultpassword",
    ) -> Optional[VirtualWorkspace]:
        try:
            status_log(f"Logging into workspace: '{workspace_id}' with user: {user}")
            await self.handle.login(user, password, workspace_id)
        except Exception as e:
            status_log(
                f"Failed to login to workspace '{workspace_id}'.\nerror: {e}", True
            )
            return

        try:
            status_log(f"Joining workspace: '{workspace_id}'")
            workspace_handle = await self.handle.join_workspace(workspace_id)
        except Exception as e:
            status_log(f"Could not join workspace '{workspace_id}'.\nerror: {e}", True)
            return

        vws = VirtualWorkspace(workspace_id, workspace_handle)
        self.workspaces[workspace_id] = vws
        self.make_active(vws)

        return vws


client = VirtualClient()
