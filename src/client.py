from __future__ import annotations
from typing import Optional, Dict


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


class VirtualClient:
    def __init__(self):
        self.codemp: Optional[codemp.Client] = None
        self.driver = codemp.init(lambda msg: logger.log(logger.level, msg), False)

        # bookkeeping corner
        self.__id2buffer: dict[str, VirtualBuffer] = {}
        self.__id2workspace: dict[str, VirtualWorkspace] = {}
        self.__view2buff: dict[sublime.View, VirtualBuffer] = {}

        self.__buff2workspace: bidict[VirtualBuffer, VirtualWorkspace] = bidict()
        self.__workspace2window: bidict[VirtualWorkspace, sublime.Window] = bidict()

    def valid_window(self, window: sublime.Window):
        return window in self.__workspace2window.inverse

    def valid_workspace(self, workspace: VirtualWorkspace | str):
        if isinstance(workspace, str):
            return client.__id2workspace.get(workspace) is not None

        return workspace in self.__workspace2window

    def all_workspaces(
        self, window: Optional[sublime.Window] = None
    ) -> list[VirtualWorkspace]:
        if window is None:
            return list(self.__workspace2window.keys())
        else:
            return self.__workspace2window.inverse[window]

    def workspace_from_view(self, view: sublime.View) -> Optional[VirtualWorkspace]:
        buff = self.__view2buff.get(view, None)
        return self.__buff2workspace.get(buff, None)

    def workspace_from_buffer(self, buff: VirtualBuffer) -> Optional[VirtualWorkspace]:
        return self.__buff2workspace.get(buff)

    def workspace_from_id(self, id: str) -> Optional[VirtualWorkspace]:
        return self.__id2workspace.get(id)

    def all_buffers(
        self, workspace: Optional[VirtualWorkspace | str] = None
    ) -> list[VirtualBuffer]:
        if workspace is None:
            return list(self.__buff2workspace.keys())
        else:
            if isinstance(workspace, str):
                workspace = client.__id2workspace[workspace]
            return self.__buff2workspace.inverse[workspace]

    def buffer_from_view(self, view: sublime.View) -> Optional[VirtualBuffer]:
        return self.__view2buff.get(view)

    def buffer_from_id(self, id: str) -> Optional[VirtualBuffer]:
        return self.__id2buffer.get(id)

    def view_from_buffer(self, buff: VirtualBuffer) -> sublime.View:
        return buff.view

    def disconnect(self):
        if self.codemp is None:
            return
        logger.info("disconnecting from the current client")
        # for each workspace tell it to clean up after itself.
        for vws in self.all_workspaces():
            vws.cleanup()
            self.codemp.leave_workspace(vws.id)

        self.__id2workspace.clear()
        self.__id2buffer.clear()
        self.__buff2workspace.clear()
        self.__view2buff.clear()
        self.__workspace2window.clear()
        self.codemp = None

    def connect(self, host: str, user: str, password: str):
        if self.codemp is not None:
            logger.info("Disconnecting from previous client.")
            return self.disconnect()

        self.codemp = codemp.Client(host, user, password)
        id = self.codemp.user_id()
        logger.debug(f"Connected to '{host}' as user {user} (id: {id})")

    def install_workspace(
        self, workspace: codemp.Workspace, window: sublime.Window
    ) -> VirtualWorkspace:
        # we pass the window as well so if the window changes in the mean
        # time we have the correct one!
        vws = VirtualWorkspace(workspace, window)
        self.__workspace2window[vws] = window
        self.__id2workspace[vws.id] = vws

        vws.install()

        return vws

    def uninstall_workspace(self, vws: VirtualWorkspace):
        if vws not in self.__workspace2window:
            raise

        logger.info(f"Uninstalling workspace '{vws.id}'...")
        vws.cleanup()
        del self.__id2workspace[vws.id]
        del self.__workspace2window[vws]
        self.__buff2workspace.inverse_del(vws)

    def workspaces_in_server(self):
        return self.codemp.active_workspaces() if self.codemp else []

    def user_id(self):
        return self.codemp.user_id() if self.codemp else None


client = VirtualClient()
