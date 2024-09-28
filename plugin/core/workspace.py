from __future__ import annotations
from typing import Optional, Tuple
from typing import TYPE_CHECKING
if TYPE_CHECKING:
    from ...main import CodempClientTextChangeListener
    import codemp

import sublime
import shutil
import tempfile
import logging

from .. import globals as g
from ..utils import draw_cursor_region
from ..utils import bidict
from .buffers import buffers

logger = logging.getLogger(__name__)

def add_project_folder(w: sublime.Window, folder: str, name: str = ""):
    proj: dict = w.project_data()  # pyright: ignore
    if proj is None:
        proj = {"folders": []}  # pyright: ignore, `Value` can be None

    if name == "":
        entry = {"path": folder}
    else:
        entry = {"name": name, "path": folder}

    proj["folders"].append(entry)

    w.set_project_data(proj)

def remove_project_folder(w: sublime.Window, filterstr: str):
    proj: dict = self.window.project_data()  # type:ignore
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

            bfm = buffers.lookupId(event.buffer)
            if not bfm: continue

            draw_cursor_region(bfm.view, event.start, event.end, event.user)
    sublime.set_timeout_async(_)

class WorkspaceManager():
    def __init__(self, handle: codemp.Workspace, window: sublime.Window, rootdir: str) -> None:
        self.handle: codemp.Workspace = handle
        self.window: sublime.Window = window
        self.curctl: codemp.CursorController = self.handle.cursor()
        self.rootdir: str = rootdir
        self.id: str = self.handle.id()
        self.curctl.callback(cursor_callback)

    def __del__(self):
        logger.debug(f"dropping workspace {self.id}")
        self.curctl.clear_callback()

        for buff in self.handle.buffer_list():
            if not self.handle.detach(buff):
                logger.warning(
                    f"could not detach from '{buff}' for workspace '{self.id}'."
                )

        for bfm in buffers.lookup(self):
            buffers.remove(bfm)

    def send_cursor(self, id: str, start: Tuple[int, int], end: Tuple[int, int]):
        # we can safely ignore the promise, we don't really care if everything
        # is ok for now with the cursor.
        self.curctl.send(id, start, end)

class WorkspaceRegistry():
    def __init__(self) -> None:
        self._workspaces: bidict[WorkspaceManager, sublime.Window] = bidict()

    def lookup(self, w: Optional[sublime.Window] = None) -> list[WorkspaceManager]:
        if not w:
            return list(self._workspaces.keys())
        ws = self._workspaces.inverse.get(w)
        return ws if ws else []

    def lookupId(self, wid: str) -> Optional[WorkspaceManager]:
        return next((ws for ws in self._workspaces if ws.id == wid), None)

    def add(self, wshandle: codemp.Workspace) -> WorkspaceManager:
        win = sublime.active_window()

        tmpdir = tempfile.mkdtemp(prefix="codemp_")
        name = f"{g.WORKSPACE_FOLDER_PREFIX}{wshandle.id()}"
        add_project_folder(win, tmpdir, name)

        wm = WorkspaceManager(wshandle, win, tmpdir)
        self._workspaces[wm] = win
        return wm

    def remove(self, ws: Optional[WorkspaceManager | str]):
        if isinstance(ws, str):
            ws = self.lookupId(ws)

        if not ws: return

        remove_project_folder(ws.window, f"{g.WORKSPACE_FOLDER_PREFIX}{ws.id}")
        shutil.rmtree(ws.rootdir, ignore_errors=True)
        del self._workspaces[ws]


workspaces = WorkspaceRegistry()







