from __future__ import annotations
from typing import Optional

import sublime
import logging

import codemp
from Codemp.src import globals as g
from Codemp.src.workspace import VirtualWorkspace

logger = logging.getLogger(__name__)


class VirtualClient:
    handle: Optional[codemp.Client]

    def __init__(self):
        self.driver = codemp.init(lambda msg: logger.log(logger.level, msg), False)
        self.workspaces: dict[str, VirtualWorkspace] = {}
        self.active_workspace: Optional[None] = None

    def __getitem__(self, key: str):
        return self.workspaces.get(key)

    def disconnect(self):
        if self.handle is None:
            return
        logger.info("disconnecting from the current client")
        for vws in self.workspaces.values():
            vws.cleanup()

        self.handle = None

    def connect(self, host: str, user: str, password: str):
        if self.handle is not None:
            logger.info("Disconnecting from previous client.")
            return self.disconnect()

        logger.info(f"Connecting to {host} with user {user}")
        try:
            self.handle = codemp.Client(host, user, password)

            if self.handle is not None:
                id = self.handle.user_id()
                logger.debug(f"Connected to '{host}' with user {user} and id: {id}")

        except Exception as e:
            logger.error(f"Could not connect: {e}")
            sublime.error_message(
                "Could not connect:\n Make sure the server is up.\n\
                or your credentials are correct."
            )
            raise

    def join_workspace(
        self,
        workspace_id: str,
    ) -> VirtualWorkspace:
        if self.handle is None:
            sublime.error_message("Connect to a server first.")
            raise

        logger.info(f"Joining workspace: '{workspace_id}'")
        try:
            workspace = self.handle.join_workspace(workspace_id).wait()
        except Exception as e:
            logger.error(f"Could not join workspace '{workspace_id}'.\n\nerror: {e}")
            sublime.error_message(f"Could not join workspace '{workspace_id}'")
            raise

        vws = VirtualWorkspace(workspace)
        self.workspaces[workspace_id] = vws

        return vws

    def leave_workspace(self, id: str):
        if self.handle is None:
            raise

        if self.handle.leave_workspace(id):
            logger.info(f"Leaving workspace: '{id}'")
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

    def make_active(self, ws: Optional[VirtualWorkspace]):
        if self.active_workspace == ws:
            return

        if self.active_workspace is not None:
            self.active_workspace.deactivate()

        if ws is not None:
            ws.activate()

        self.active_workspace = ws  # pyright: ignore


client = VirtualClient()
