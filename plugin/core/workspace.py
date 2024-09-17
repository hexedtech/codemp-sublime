from __future__ import annotations
from typing import Optional, Tuple
from typing import TYPE_CHECKING
if TYPE_CHECKING:
    from ...main import CodempClientTextChangeListener
    from ...lib import codemp

import sublime
import shutil
import tempfile
import logging

from .. import globals as g
from .buffers import VirtualBuffer
from ..utils import draw_cursor_region
from ..utils import bidict
from ..core.registry import buffers

logger = logging.getLogger(__name__)

# def make_cursor_callback(workspace: VirtualWorkspace):
#     def _callback(ctl: codemp.CursorController):
#         def _():
#             while event := ctl.try_recv().wait():
#                 logger.debug("received remote cursor movement!")
#                 if event is None:
#                     break

#                 vbuff = workspace.buff_by_id(event.buffer)
#                 if vbuff is None:
#                     logger.warning(
#                         f"{workspace.id} received a cursor event for a buffer that wasn't saved internally."
#                     )
#                     continue

#                 draw_cursor_region(vbuff.view, event.start, event.end, event.user)

#         sublime.set_timeout_async(_)

#     return _callback


# # A virtual workspace is a bridge class that aims to translate
# # events that happen to the codemp workspaces into sublime actions
# class VirtualWorkspace:
#     def __init__(self, handle: codemp.Workspace, window: sublime.Window):
#         self.handle: codemp.Workspace = handle
#         self.window: sublime.Window = window
#         self.curctl: codemp.CursorController = self.handle.cursor()

#         self.id: str = self.handle.id()

#         self.handle.fetch_buffers()
#         self.handle.fetch_users()

#         self._id2buff: dict[str, VirtualBuffer] = {}

#         tmpdir = tempfile.mkdtemp(prefix="codemp_")
#         self.rootdir = tmpdir

#         proj: dict = self.window.project_data()  # pyright: ignore
#         if proj is None:
#             proj = {"folders": []}  # pyright: ignore, Value can be None

#         proj["folders"].append(
#             {"name": f"{g.WORKSPACE_FOLDER_PREFIX}{self.id}", "path": self.rootdir}
#         )
#         self.window.set_project_data(proj)

#         self.curctl.callback(make_cursor_callback(self))
#         self.isactive = True

#     def __del__(self):
#         logger.debug("workspace destroyed!")

#     def __hash__(self) -> int:
#         # so we can use these as dict keys!
#         return hash(self.id)

#     def uninstall(self):
#         self.curctl.clear_callback()
#         self.isactive = False
#         self.curctl.stop()

#         for vbuff in self._id2buff.values():
#             vbuff.uninstall()
#             if not self.handle.detach(vbuff.id):
#                 logger.warning(
#                     f"could not detach from '{vbuff.id}' for workspace '{self.id}'."
#                 )
#         self._id2buff.clear()

#         proj: dict = self.window.project_data()  # type:ignore
#         if proj is None:
#             raise

#         clean_proj_folders = list(
#             filter(
#                 lambda f: f.get("name", "") != f"{g.WORKSPACE_FOLDER_PREFIX}{self.id}",
#                 proj["folders"],
#             )
#         )
#         proj["folders"] = clean_proj_folders
#         self.window.set_project_data(proj)

#         logger.info(f"cleaning up virtual workspace '{self.id}'")
#         shutil.rmtree(self.rootdir, ignore_errors=True)

#     def install_buffer(
#         self, buff: codemp.BufferController, listener: CodempClientTextChangeListener
#     ) -> VirtualBuffer:
#         logger.debug(f"installing buffer {buff.path()}")

#         view = self.window.new_file()
#         vbuff = VirtualBuffer(buff, view, self.rootdir)
#         self._id2buff[vbuff.id] = vbuff

#         vbuff.sync(listener)

#         return vbuff

def add_project_folder(w: sublime.Window, folder: str, name: str = ""):
    proj: dict = w.project_data()  # pyright: ignore
    if proj is None:
        proj = {"folders": []}  # pyright: ignore, Value can be None

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

class WorkspaceManager():
    def __init__(self, handle: codemp.Workspace, window: sublime.Window, rootdir: str) -> None:
        self.handle: codemp.Workspace = handle
        self.window: sublime.Window = window
        self.curctl: codemp.CursorController = self.handle.cursor()
        self.rootdir: str = rootdir

        self.id = self.handle.id()

    def __del__(self):
        self.curctl.clear_callback()
        self.curctl.stop()

        # TODO: STUFF WITH THE BUFFERS IN THE REGISTRY

        for buff in self.handle.buffer_list():
            if not self.handle.detach(buff):
                logger.warning(
                    f"could not detach from '{buff}' for workspace '{self.id}'."
                )


    def send_cursor(self, id: str, start: Tuple[int, int], end: Tuple[int, int]):
        # we can safely ignore the promise, we don't really care if everything
        # is ok for now with the cursor.
        self.curctl.send(id, start, end)



class WorkspaceRegistry():
    def __init__(self) -> None:
        self._workspaces: bidict[WorkspaceManager, sublime.Window] = bidict()

    def lookup(self, w: sublime.Window | None = None) -> list[WorkspaceManager]:
        if not w:
            return list(self._workspaces.keys())
        ws = self._workspaces.inverse.get(w)
        return ws if ws else []

    def lookupId(self, wid: str) -> WorkspaceManager | None:
        return next((ws for ws in self._workspaces if ws.id == wid), None)

    def add(self, wshandle: codemp.Workspace):
        win = sublime.active_window()

        tmpdir = tempfile.mkdtemp(prefix="codemp_")
        name = f"{g.WORKSPACE_FOLDER_PREFIX}{wshandle.id()}"
        add_project_folder(win, tmpdir, name)

        wm = WorkspaceManager(wshandle, win, tmpdir)
        self._workspaces[wm] = win

    def remove(self, ws: WorkspaceManager | str | None):
        if isinstance(ws, str):
            ws = self.lookupId(ws)

        if not ws:
            return

        remove_project_folder(ws.window, f"{g.WORKSPACE_FOLDER_PREFIX}{ws.id}")
        shutil.rmtree(ws.rootdir, ignore_errors=True)
        del self._workspaces[ws]










