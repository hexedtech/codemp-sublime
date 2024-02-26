from __future__ import annotations
from typing import Optional, Callable


import sublime
import asyncio
import tempfile
import os
import shutil


import Codemp.src.globals as g
from Codemp.src.wrappers import BufferController, Workspace, Client
from Codemp.src.utils import status_log, rowcol_to_region
from Codemp.src.TaskManager import TaskManager


# This class is used as an abstraction between the local buffers (sublime side) and the
# remote buffers (codemp side), to handle the syncronicity.
# This class is mainly manipulated by a VirtualWorkspace, that manages its buffers
# using this abstract class
class VirtualBuffer:
    def __init__(
        self,
        workspace: VirtualWorkspace,
        remote_id: str,
        view: sublime.View,
        buffctl: BufferController,
    ):
        self.view = view
        self.codemp_id = remote_id
        self.sublime_id = view.buffer_id()

        self.workspace = workspace
        self.buffctl = buffctl

        self.tmpfile = os.path.join(workspace.rootdir, self.codemp_id)

        self.view.set_name(self.codemp_id)
        open(self.tmpfile, "a").close()
        self.view.retarget(self.tmpfile)
        self.view.set_scratch(True)

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
        # this does nothing for now. figure out a way later
        # self.view.erase_regions(g.SUBLIME_REGIONS_PREFIX)
        status_log(f"cleaning up virtual buffer '{self.codemp_id}'")


# A virtual workspace is a bridge class that aims to translate
# events that happen to the codemp workspaces into sublime actions
class VirtualWorkspace:
    def __init__(self, client: VirtualClient, workspace_id: str, handle: Workspace):
        self.id = workspace_id
        self.sublime_window = sublime.active_window()
        self.client = client
        self.handle = handle
        self.curctl = handle.cursor()

        # mapping remote ids -> local ids
        self.id_map: dict[str, str] = {}
        self.active_buffers: dict[str, VirtualBuffer] = {}  # local_id -> VBuff

        # initialise the virtual filesystem
        tmpdir = tempfile.mkdtemp(prefix="codemp_")
        status_log("setting up virtual fs for workspace in: {} ".format(tmpdir))
        self.rootdir = tmpdir

        # and add a new "project folder"
        proj_data = self.sublime_window.project_data()
        if proj_data is None:
            proj_data = {"folders": []}

        proj_data["folders"].append(
            {"name": f"{g.WORKSPACE_FOLDER_PREFIX}{self.id}", "path": self.rootdir}
        )
        self.sublime_window.set_project_data(proj_data)

        s: dict = self.sublime_window.settings()
        if s.get(g.CODEMP_WINDOW_TAG, False):
            s[g.CODEMP_WINDOW_WORKSPACES].append(self.id)
        else:
            s[g.CODEMP_WINDOW_TAG] = True
            s[g.CODEMP_WINDOW_WORKSPACES] = [self.id]

    def add_buffer(self, remote_id: str, vbuff: VirtualBuffer):
        self.id_map[remote_id] = vbuff.view.buffer_id()
        self.active_buffers[vbuff.view.buffer_id()] = vbuff

    def cleanup(self):
        # the worskpace only cares about closing the various open views on its buffers.
        # the event listener calls the cleanup code for each buffer independently on its own.
        for vbuff in self.active_buffers.values():
            vbuff.view.close()

        self.active_buffers = {}  # drop all buffers, let them be garbace collected (hopefully)

        d = self.sublime_window.project_data()
        newf = list(
            filter(
                lambda F: F["name"] != f"{g.WORKSPACE_FOLDER_PREFIX}{self.id}",
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

    def get_by_local(self, local_id: str) -> Optional[VirtualBuffer]:
        return self.active_buffers.get(local_id)

    def get_by_remote(self, remote_id: str) -> Optional[VirtualBuffer]:
        return self.active_buffers.get(self.id_map.get(remote_id))

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

        view = self.sublime_window.new_file()
        vbuff = VirtualBuffer(self, id, view, buff_ctl)
        self.add_buffer(id, vbuff)

        self.client.spawn_buffer_manager(vbuff)

        # TODO! if the view is already active calling focus_view() will not trigger the on_activate
        self.sublime_window.focus_view(view)


class VirtualClient:
    def __init__(self, on_exit: Callable = None):
        self.handle: Client = Client()
        self.workspaces: dict[str, VirtualWorkspace] = {}
        self.active_workspace: VirtualWorkspace = None
        self.tm = TaskManager(on_exit)

    def __getitem__(self, key: str):
        return self.workspaces.get(key)

    def make_active(self, ws: VirtualWorkspace):
        # TODO: Logic to deal with swapping to and from workspaces,
        # what happens to the cursor tasks etc..
        if self.active_workspace is not None:
            self.tm.stop_and_pop(f"{g.CURCTL_TASK_PREFIX}-{self.active_workspace.id}")
        self.active_workspace = ws
        self.spawn_cursor_manager(ws)

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
        self, workspace_id: str, user="sublime", password="lmaodefaultpassword"
    ) -> VirtualWorkspace:
        try:
            status_log(f"Logging into workspace: '{workspace_id}'")
            await self.handle.login(user, password, workspace_id)
        except Exception as e:
            status_log(f"Failed to login to workspace '{workspace_id}'.\nerror: {e}")
            sublime.error_message(
                f"Failed to login to workspace '{workspace_id}'.\nerror: {e}"
            )
            return

        try:
            status_log(f"Joining workspace: '{workspace_id}'")
            workspace_handle = await self.handle.join_workspace(workspace_id)
        except Exception as e:
            status_log(f"Could not join workspace '{workspace_id}'.\nerror: {e}")
            sublime.error_message(
                f"Could not join workspace '{workspace_id}'.\nerror: {e}"
            )
            return

        vws = VirtualWorkspace(self, workspace_id, workspace_handle)
        self.make_active(vws)
        self.workspaces[workspace_id] = vws

        return vws

    def spawn_cursor_manager(self, virtual_workspace: VirtualWorkspace):
        async def move_cursor_task(vws):
            status_log(f"spinning up cursor worker for workspace '{vws.id}'...")
            try:
                while cursor_event := await vws.curctl.recv():
                    vbuff = vws.get_by_remote(cursor_event.buffer)

                    if vbuff is None:
                        status_log(
                            f"Received a cursor event for an unknown \
                            or inactive buffer: {cursor_event.buffer}"
                        )
                        continue

                    reg = rowcol_to_region(
                        vbuff.view, cursor_event.start, cursor_event.end
                    )
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
                status_log(f"cursor worker for '{vws.id}' stopped...")
                raise
            except Exception as e:
                status_log(f"cursor worker '{vws.id}' crashed:\n{e}")
                raise

        self.tm.dispatch(
            move_cursor_task(virtual_workspace),
            f"{g.CURCTL_TASK_PREFIX}-{virtual_workspace.id}",
        )

    def send_cursor(self, vbuff: VirtualBuffer):
        # TODO: only the last placed cursor/selection.
        status_log(f"sending cursor position in workspace: {vbuff.workspace.id}")
        region = vbuff.view.sel()[0]
        start = vbuff.view.rowcol(region.begin())  # only counts UTF8 chars
        end = vbuff.view.rowcol(region.end())

        vbuff.workspace.curctl.send(vbuff.codemp_id, start, end)

    def spawn_buffer_manager(self, vbuff: VirtualBuffer):
        async def apply_buffer_change_task(vb):
            status_log(f"spinning up '{vb.codemp_id}' buffer worker...")
            try:
                while text_change := await vb.buffctl.recv():
                    if text_change.is_empty():
                        status_log("change is empty. skipping.")
                        continue
                    # In case a change arrives to a background buffer, just apply it.
                    # We are not listening on it. Otherwise, interrupt the listening
                    # to avoid echoing back the change just received.
                    if vb.view.id() == g.ACTIVE_CODEMP_VIEW:
                        status_log(
                            "received a text change with view active, stopping the echo."
                        )
                        vb.view.settings()[g.CODEMP_IGNORE_NEXT_TEXT_CHANGE] = True

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
                status_log(f"'{vb.codemp_id}' buffer worker stopped...")
                raise
            except Exception as e:
                status_log(f"buffer worker '{vb.codemp_id}' crashed:\n{e}")
                raise

        self.tm.dispatch(
            apply_buffer_change_task(vbuff),
            f"{g.BUFFCTL_TASK_PREFIX}-{vbuff.codemp_id}",
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
