from __future__ import annotations

import sublime
import logging

from codemp import Client
from Codemp.src import globals as g
from Codemp.src.workspace import VirtualWorkspace

logger = logging.getLogger(__name__)


class VirtualClient:
    def __init__(self):
        self.handle = None
        self.workspaces: dict[str, VirtualWorkspace] = {}
        self.active_workspace: VirtualWorkspace | None = None

    def __getitem__(self, key: str):
        return self.workspaces.get(key)

    def connect(self, host: str, user: str, password: str):
        logger.info(f"Connecting to {host} with user {user}")
        try:
            self.handle = Client(host, user, password)
        except Exception as e:
            logger.error(f"Could not connect: {e}")
            sublime.error_message(
                "Could not connect:\n Make sure the server is up.\n\
                or your credentials are correct."
            )
            return

        id = self.handle.user_id()  # pyright: ignore
        logger.debug(f"Connected to '{host}' with user {user} and id: {id}")

    def join_workspace(
        self,
        workspace_id: str,
    ) -> VirtualWorkspace | None:
        if self.handle is None:
            return

        logger.info(f"Joining workspace: '{workspace_id}'")
        try:
            workspace = self.handle.join_workspace(workspace_id)
        except Exception as e:
            logger.error(f"Could not join workspace '{workspace_id}'.\n\nerror: {e}")
            sublime.error_message(f"Could not join workspace '{workspace_id}'")
            return

        vws = VirtualWorkspace(workspace)
        self.workspaces[workspace_id] = vws

        return vws

    def leave_workspace(self, id: str):
        if self.handle is None:
            return False
        logger.info(f"Leaving workspace: '{id}'")
        if self.handle.leave_workspace(id):
            self.workspaces[id].cleanup()
            del self.workspaces[id]

    def get_workspace(self, view):
        tag_id = view.settings().get(g.CODEMP_WORKSPACE_ID)
        if tag_id is None:
            return

        ws = self.workspaces.get(tag_id)
        if ws is None:
            logging.warning("a tag on the view was found but not a matching workspace.")
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


client = VirtualClient()
