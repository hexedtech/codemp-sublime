from __future__ import annotations
from typing import Optional, Tuple
from typing import TYPE_CHECKING
if TYPE_CHECKING:
    import codemp

import sublime
import shutil
import tempfile
import logging

from codemp import Selection, Event
from .. import globals as g
from ..utils import draw_cursor_region
from ..utils import bidict

from .session import session
from .buffers import buffers

logger = logging.getLogger(__name__)

def add_project_folder(w: sublime.Window, folder: str, name: str = ""):
    proj = w.project_data()
    if not isinstance(proj, dict):
        proj = {"folders": []}

    if name == "":
        entry = {"path": folder}
    else:
        entry = {"name": name, "path": folder}

    proj["folders"].append(entry)

    w.set_project_data(proj)

def remove_project_folder(w: sublime.Window, filterstr: str):
    proj: dict = w.project_data()  # type:ignore
    if proj is None:
        return

    clean_proj_folders = list(
        filter(
            lambda f: f.get("name", "") != filterstr,
            proj["folders"],
        )
    )
    proj["folders"] = clean_proj_folders
    w.set_project_data(proj)


def cursor_callback(ctl: codemp.CursorController):
    def _():
        while event := ctl.try_recv().wait():
            if event is None: break
            
            try: bfm = buffers.lookupId(event.sel.buffer)
            except KeyError: continue

            region_start = (event.sel.start_row, event.sel.start_col)
            region_end = (event.sel.end_row, event.sel.end_col)

            draw_cursor_region(bfm.view, region_start, region_end, event.user)
    sublime.set_timeout_async(_)

def workspace_callback(ws: codemp.Workspace):
    # TODO: create a dedicated panel for codemp events and notifications.
    def _():
        while event := ws.try_recv().wait():
            if event is None: break

            if isinstance(event, Event.FileTreeUpdated):                                #type:ignore
                logger.debug(f"received a FileTree Event for workspace: {ws.id} - {event.path}")  #type:ignore

            if isinstance(event, Event.UserJoin):                                       #type:ignore
                logger.debug(f"User '{event.name}' joined the workspace '{ws.id}'")     #type:ignore

            if isinstance(event, Event.UserLeave):                                      #type:ignore
                logger.debug(f"User '{event.name}' left the workspace '{ws.id}'")       #type:ignore
    sublime.set_timeout_async(_)

class WorkspaceManager():
    def __init__(self, handle: codemp.Workspace, window: sublime.Window, rootdir: str) -> None:
        self.handle: codemp.Workspace = handle
        self.window: sublime.Window = window
        self.curctl: codemp.CursorController = self.handle.cursor()
        self.rootdir: str = rootdir
        self.id: str = self.handle.id()
        self.handle.callback(workspace_callback)
        self.curctl.callback(cursor_callback)

    def __del__(self):
        logger.debug(f"dropping workspace {self.id}")
        self.curctl.clear_callback()
        self.handle.clear_callback()

        for buff in self.handle.active_buffers():
            if not self.handle.detach_buffer(buff):
                logger.warning(
                    f"could not detach from '{buff}' for workspace '{self.id}'."
                )

        for bfm in buffers.lookup(self):
            buffers.remove(bfm)

    def send_cursor(self, id: str, start: Tuple[int, int], end: Tuple[int, int]):
        # we can safely ignore the promise, we don't really care if everything
        # is ok for now with the cursor.
        sel = Selection(
            start_row=start[0],
            start_col=start[1],
            end_row=end[0],
            end_col=end[1],
            buffer=id
        )
        self.curctl.send(sel)

class WorkspaceRegistry():
    def __init__(self) -> None:
        self._workspaces: bidict[WorkspaceManager, sublime.Window] = bidict()

    def __contains__(self, item: str):
        try: self.lookupId(item)
        except KeyError: return False
        return True

    def hasactive(self):
        return len(self._workspaces.keys()) > 0

    def lookup(self, w: Optional[sublime.Window] = None) -> list[WorkspaceManager]:
        if not w:
            return list(self._workspaces.keys())
        ws = self._workspaces.inverse.get(w)
        return ws if ws else []

    def lookupParent(self, ws: WorkspaceManager | str) -> sublime.Window:
        if isinstance(ws, str):
            ws = self.lookupId(ws)
        return self._workspaces[ws]

    def lookupId(self, wid: str) -> WorkspaceManager:
        wsm = next((ws for ws in self._workspaces if ws.id == wid), None)
        if not wsm: raise KeyError
        return wsm

    def register(self, wid: str) -> WorkspaceManager:
        win = sublime.active_window()

        # tmpdir = tempfile.mkdtemp(prefix="codemp_")
        # add_project_folder(win, tmpdir, f"{g.WORKSPACE_FOLDER_PREFIX}{wshandle.id()}")
        try:
            ws = session.client.attach_workspace(wid).wait()
        except Exception as e:
            logger.error(f"Could not join workspace '{wid}': {e}")
            sublime.error_message(f"Could not join workspace '{wid}'")
            raise e
        logger.debug("Joined! Adding workspace to registry")

        tmpdir = "DISABLED"
        wm = WorkspaceManager(ws, win, tmpdir)
        self._workspaces[wm] = win

        return wm

    def remove(self, ws: WorkspaceManager | str):
        if isinstance(ws, str):
            ws = self.lookupId(ws)

        logger.debug("removing all the buffers from the workspace")
        # we need ids, we can't keep references to the buffermanager here
        bufferlist = [buff.id for buff in buffers.lookup(ws)]
        for buff in bufferlist:
            logger.debug("removing the buffer {}".format(buff))
            buffers.remove(buff)

        del self._workspaces[ws]

        ws = ws.id
        if not session.client.leave_workspace(ws):
            logger.error(f"could not leave the workspace '{ws}'")
        else:
            logger.debug(f"successfully left the workspace '{ws}'")



workspaces = WorkspaceRegistry()







