from __future__ import annotations
from typing import Optional

import sublime
import random
import asyncio
import tempfile
import os
import shutil

from codemp import (
    BufferController,
    Workspace,
    Client,
    PyLogger,
)
from sublime_plugin import attach_buffer
from ..src import globals as g
from ..src.TaskManager import tm
from ..src.utils import status_log, rowcol_to_region


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
        except asyncio.CancelledError:
            status_log("stopping logger")
            self.started = False
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
        buffctl: BufferController,
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
                change_id = self.view.change_id()
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
                        "start": text_change.start,
                        "end": text_change.end,
                        "content": text_change.content,
                        "change_id": change_id,
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
            self.buffctl.send(region.begin(), region.end(), change.str)

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
    def __init__(self, handle: Workspace):
        self.handle = handle
        self.id = self.handle.id()
        self.sublime_window = sublime.active_window()
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

        self.curctl.stop()

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
                "[WARN] a local-remote buffer id pair was found but \
                not the matching virtual buffer."
            )
            return

        return vbuff

    # A workspace has some buffers inside of it (filetree)
    # some of those you are already attached to (buffers_by_name)
    # If already attached to it return the same alredy existing bufferctl
    # if existing but not attached (attach)
    # if not existing ask for creation (create + attach)
    async def attach(self, id: str):
        if id is None:
            return

        attached_buffers = self.handle.buffer_by_name(id)
        if attached_buffers is not None:
            return self.get_by_remote(id)

        await self.handle.fetch_buffers()
        existing_buffers = self.handle.filetree()
        if id not in existing_buffers:
            create = sublime.ok_cancel_dialog(
                "There is no buffer named '{id}' in the workspace.\n\
                Do you want to create it?",
                ok_title="yes",
                title="Create Buffer?",
            )
            if create:
                try:
                    await self.handle.create(id)
                except Exception as e:
                    status_log(f"could not create buffer:\n\n {e}", True)
                    return
            else:
                return

        # now either we created it or it exists already
        try:
            buff_ctl = await self.handle.attach(id)
        except Exception as e:
            status_log(f"error when attaching to buffer '{id}':\n\n {e}", True)
            return

        vbuff = VirtualBuffer(self, id, buff_ctl)
        self.add_buffer(id, vbuff)

        # TODO! if the view is already active calling focus_view() will not trigger the on_activate
        self.sublime_window.focus_view(vbuff.view)

    def detach(self, id: str):
        if id is None:
            return

        attached_buffers = self.handle.buffer_by_name(id)
        if attached_buffers is None:
            status_log(f"You are not attached to the buffer '{id}'", True)
            return

        self.handle.detach(id)

    async def delete(self, id: str):
        if id is None:
            return

        # delete a non existent buffer
        await self.handle.fetch_buffers()
        existing_buffers = self.handle.filetree()
        if id not in existing_buffers:
            status_log(f"The buffer '{id}' does not exists.", True)
            return
        # delete a buffer that exists but you are not attached to
        attached_buffers = self.handle.buffer_by_name(id)
        if attached_buffers is None:
            delete = sublime.ok_cancel_dialog(
                "Confirm you want to delete the buffer '{id}'",
                ok_title="delete",
                title="Delete Buffer?",
            )
            if delete:
                try:
                    await self.handle.delete(id)
                except Exception as e:
                    status_log(f"error when deleting the buffer '{id}':\n\n {e}", True)
                    return
            else:
                return

        # delete buffer that you are attached to
        delete = sublime.ok_cancel_dialog(
            "Confirm you want to delete the buffer '{id}'.\n\
            You will be disconnected from it.",
            ok_title="delete",
            title="Delete Buffer?",
        )
        if delete:
            self.detach(id)
            try:
                await self.handle.delete(id)
            except Exception as e:
                status_log(f"error when deleting the buffer '{id}':\n\n {e}", True)
                return

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
        self.handle = None
        self.workspaces: dict[str, VirtualWorkspace] = {}
        self.active_workspace: Optional[VirtualWorkspace] = None

    def __getitem__(self, key: str):
        return self.workspaces.get(key)

    def connect(self, host: str, user: str, password: str):
        status_log(f"Connecting to {host} with user {user}")
        try:
            self.handle = Client(host, user, password)
        except Exception as e:
            sublime.error_message(
                f"Could not connect:\n Make sure the server is up.\n\
                or your credentials are correct\n\nerror: {e}"
            )
            return

        id = self.handle.user_id()
        status_log(f"Connected to '{host}' with user {user} and id: {id}")

    async def join_workspace(
        self,
        workspace_id: str,
    ) -> Optional[VirtualWorkspace]:
        if self.handle is None:
            status_log("Connect to a server first!", True)
            return

        status_log(f"Joining workspace: '{workspace_id}'")
        try:
            workspace = await self.handle.join_workspace(workspace_id)
        except Exception as e:
            status_log(
                f"Could not join workspace '{workspace_id}'.\n\nerror: {e}", True
            )
            return

        vws = VirtualWorkspace(workspace)
        self.workspaces[workspace_id] = vws
        self.make_active(vws)

        return vws

    def leave_workspace(self, id: str):
        if self.handle is None:
            status_log("Connect to a server first!", True)
            return False
        status_log(f"Leaving workspace: '{id}'")
        return self.handle.leave_workspace(id)

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

    def active_workspaces(self):
        return self.handle.active_workspaces() if self.handle else []

    def user_id(self):
        return self.handle.user_id() if self.handle else None

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


DEBUG = False
logger = CodempLogger(DEBUG)
logger.log()
client = VirtualClient()
