from __future__ import annotations
from typing import Optional


import sublime
import logging

import codemp
from Codemp.src import globals as g
from Codemp.src.workspace import VirtualWorkspace
from Codemp.src.buffers import VirtualBuffer
from Codemp.src.utils import bidict

logger = logging.getLogger(__name__)


# the client will be responsible to keep track of everything!
# it will need 3 bidirectional dictionaries and 2 normal ones
# normal: workspace_id -> VirtualWorkspaces
# normal: buffer_id -> VirtualBuffer
# bidir: VirtualBuffer <-> VirtualWorkspace
# bidir: VirtualBuffer <-> Sublime.View
# bidir: VirtualWorkspace <-> Sublime.Window
def log_async(msg):
    sublime.set_timeout_async(lambda: logger.log(logger.level, msg))


class VirtualClient:
    def __init__(self):
        self.codemp: Optional[codemp.Client] = None
        self.driver: Optional[codemp.Driver] = None

        # bookkeeping corner
        self._id2buffer: dict[str, VirtualBuffer] = {}
        self._id2workspace: dict[str, VirtualWorkspace] = {}

        self._view2buff: dict[sublime.View, VirtualBuffer] = {}
        self._buff2workspace: bidict[VirtualBuffer, VirtualWorkspace] = bidict()
        # self._workspace2window: bidict[VirtualWorkspace, sublime.Window] = bidict()
        self._workspace2window: dict[VirtualWorkspace, sublime.Window] = bidict()

    def dump(self):
        logger.debug("CLIENT STATUS:")
        logger.debug("WORKSPACES:")
        logger.debug(f"{self._id2workspace}")
        logger.debug(f"{self._workspace2window}")
        logger.debug(f"{self._buff2workspace}")
        logger.debug(f"{self._buff2workspace.inverse}")
        logger.debug("VIEWS")
        logger.debug(f"{self._view2buff}")
        logger.debug(f"{self._id2buffer}")

    def all_workspaces(
        self, window: Optional[sublime.Window] = None
    ) -> list[VirtualWorkspace]:
        if window is None:
            return list(self._workspace2window.keys())
        else:
            return [
                ws
                for ws in self._workspace2window
                if self._workspace2window[ws] == window
            ]

    def workspace_from_view(self, view: sublime.View) -> Optional[VirtualWorkspace]:
        buff = self._view2buff.get(view, None)
        return self.workspace_from_buffer(buff) if buff is not None else None

    def workspace_from_buffer(self, vbuff: VirtualBuffer) -> Optional[VirtualWorkspace]:
        return self._buff2workspace.get(vbuff, None)

    def workspace_from_id(self, id: str) -> Optional[VirtualWorkspace]:
        return self._id2workspace.get(id)

    def all_buffers(
        self, workspace: Optional[VirtualWorkspace | str] = None
    ) -> list[VirtualBuffer]:
        if workspace is None:
            return list(self._id2buffer.values())
        elif isinstance(workspace, str):
            workspace = client._id2workspace[workspace]
            return self._buff2workspace.inverse.get(workspace, [])
        else:
            return self._buff2workspace.inverse.get(workspace, [])

    def buffer_from_view(self, view: sublime.View) -> Optional[VirtualBuffer]:
        return self._view2buff.get(view)

    def buffer_from_id(self, id: str) -> Optional[VirtualBuffer]:
        return self._id2buffer.get(id)

    def view_from_buffer(self, buff: VirtualBuffer) -> sublime.View:
        return buff.view

    def register_buffer(self, workspace: VirtualWorkspace, buffer: VirtualBuffer):
        self._buff2workspace[buffer] = workspace
        self._id2buffer[buffer.id] = buffer
        self._view2buff[buffer.view] = buffer

    def disconnect(self):
        if self.codemp is None:
            return
        logger.info("disconnecting from the current client")
        # for each workspace tell it to clean up after itself.
        for vws in self.all_workspaces():
            self.codemp.leave_workspace(vws.id)

        self._id2workspace.clear()
        self._id2buffer.clear()
        self._buff2workspace.clear()
        self._view2buff.clear()
        self._workspace2window.clear()
        self.codemp = None

    def connect(self, host: str, user: str, password: str):
        if self.codemp is not None:
            logger.info("Disconnecting from previous client.")
            return self.disconnect()

        if self.driver is None:
            self.driver = codemp.init()
            codemp.set_logger(log_async, False)

        self.codemp = codemp.connect(host, user, password).wait()
        id = self.codemp.user_id()
        logger.debug(f"Connected to '{host}' as user {user} (id: {id})")

    def install_workspace(self, workspace: codemp.Workspace, window: sublime.Window):
        vws = VirtualWorkspace(workspace, window)
        self._workspace2window[vws] = window
        self._id2workspace[vws.id] = vws

    def uninstall_workspace(self, vws: VirtualWorkspace):
        # we aim at dropping all references to the workspace
        # as well as all the buffers associated with it.
        # if we did a good job the dunder del method will kick
        # and continue with the cleanup.
        logger.info(f"Uninstalling workspace '{vws.id}'...")
        del self._workspace2window[vws]
        del self._id2workspace[vws.id]
        for vbuff in self.all_buffers(vws):
            self.unregister_buffer(vbuff)
        del vws
        # self._buff2workspace.inverse_del(vws) - if we delete all straight
        # keys the last delete will remove also the empty key.

    def unregister_buffer(self, buffer: VirtualBuffer):
        del self._buff2workspace[buffer]
        del self._id2buffer[buffer.id]
        del self._view2buff[buffer.view]

    def workspaces_in_server(self):
        return self.codemp.active_workspaces() if self.codemp else []

    def user_id(self):
        return self.codemp.user_id() if self.codemp else None


client = VirtualClient()
