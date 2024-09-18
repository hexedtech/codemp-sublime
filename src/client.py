from __future__ import annotations
from typing import Optional


import sublime
import logging

import codemp
from .workspace import VirtualWorkspace
from .buffers import VirtualBuffer
from .utils import bidict

logger = logging.getLogger(__name__)

# the client will be responsible to keep track of everything!
# it will need 3 bidirectional dictionaries and 2 normal ones
# normal: workspace_id -> VirtualWorkspaces
# normal: buffer_id -> VirtualBuffer
# bidir: VirtualBuffer <-> VirtualWorkspace
# bidir: VirtualBuffer <-> Sublime.View
# bidir: VirtualWorkspace <-> Sublime.Window


class VirtualClient:
    def __init__(self):
        self.codemp: Optional[codemp.Client] = None
        self.driver: Optional[codemp.Driver] = None

        # bookkeeping corner
        self._id2buffer: dict[str, VirtualBuffer] = {}
        self._id2workspace: dict[str, VirtualWorkspace] = {}

        self._view2buff: dict[sublime.View, VirtualBuffer] = {}
        self._buff2workspace: bidict[VirtualBuffer, VirtualWorkspace] = bidict()
        self._workspace2window: dict[VirtualWorkspace, sublime.Window] = {}

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
            self.uninstall_workspace(vws)
            self.codemp.leave_workspace(vws.id)

        self._id2workspace.clear()
        self._id2buffer.clear()
        self._buff2workspace.clear()
        self._view2buff.clear()
        self._workspace2window.clear()
    
        if self.driver is not None:
            self.driver.stop()
            self.driver = None
        self.codemp = None

    def connect(self, host: str, user: str, password: str):
        if self.codemp is not None:
            logger.info("Disconnecting from previous client.")
            return self.disconnect()

        if self.driver is None:
            self.driver = codemp.init()
            logger.debug("registering logger callback...")
            if not codemp.set_logger(lambda msg: logger.debug(msg), False):
                logger.debug(
                    "could not register the logger... If reconnecting it's ok, the previous logger is still registered"
                )

        config = codemp.get_default_config()
        config.username = user
        config.host = host
        config.password = password

        self.codemp = codemp.connect(config).wait()
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

        vws.uninstall()

    def unregister_buffer(self, buffer: VirtualBuffer):
        del self._buff2workspace[buffer]
        del self._id2buffer[buffer.id]
        del self._view2buff[buffer.view]

    def workspaces_in_server(self):
        return self.codemp.active_workspaces() if self.codemp else []

    def user_id(self):
        return self.codemp.user_id() if self.codemp else None


client = VirtualClient()
