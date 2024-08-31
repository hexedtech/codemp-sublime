from __future__ import annotations
from typing import Optional, Tuple

import sublime
import shutil
import tempfile
import logging

import codemp
from Codemp.src import globals as g
from Codemp.src.buffers import VirtualBuffer
from Codemp.src.utils import draw_cursor_region
from Codemp.src.utils import bidict


logger = logging.getLogger(__name__)


def make_cursor_callback(workspace: VirtualWorkspace):
    def _callback(ctl: codemp.CursorController):
        def get_event_and_draw():
            while event := ctl.try_recv().wait():
                logger.debug("received remote cursor movement!")
                if event is None:
                    break

                vbuff = workspace.buff_by_id(event.buffer)
                if vbuff is None:
                    logger.warning(
                        "received a cursor event for a buffer that wasn't saved internally."
                    )
                    continue

                draw_cursor_region(vbuff.view, event.start, event.end, event.user)

        sublime.set_timeout_async(get_event_and_draw)

    return _callback


# A virtual workspace is a bridge class that aims to translate
# events that happen to the codemp workspaces into sublime actions
class VirtualWorkspace:
    def __init__(self, handle: codemp.Workspace, window: sublime.Window):
        self.codemp: codemp.Workspace = handle
        self.window: sublime.Window = window
        self.curctl: codemp.CursorController = self.codemp.cursor()

        self.id: str = self.codemp.id()

        self.codemp.fetch_buffers()
        self.codemp.fetch_users()

        self._buff2view: bidict[VirtualBuffer, sublime.View] = bidict()
        self._id2buff: dict[str, VirtualBuffer] = {}

        tmpdir = tempfile.mkdtemp(prefix="codemp_")
        logging.debug(f"setting up virtual fs for workspace in: {tmpdir}")
        self.rootdir = tmpdir

        proj: dict = self.window.project_data()  # pyright: ignore
        if proj is None:
            proj = {"folders": []}  # pyright: ignore, Value can be None

        proj["folders"].append(
            {"name": f"{g.WORKSPACE_FOLDER_PREFIX}{self.id}", "path": self.rootdir}
        )
        self.window.set_project_data(proj)

        self.curctl.callback(make_cursor_callback(self))
        self.isactive = True

    def __del__(self):
        self.curctl.clear_callback()
        self.isactive = False
        self.curctl.stop()

        proj: dict = self.window.project_data()  # type:ignore
        if proj is None:
            raise

        clean_proj_folders = list(
            filter(
                lambda f: f.get("name", "") != f"{g.WORKSPACE_FOLDER_PREFIX}{self.id}",
                proj["folders"],
            )
        )
        proj["folders"] = clean_proj_folders
        self.window.set_project_data(proj)

        logger.info(f"cleaning up virtual workspace '{self.id}'")
        shutil.rmtree(self.rootdir, ignore_errors=True)

        if not all(self.codemp.detach(buff) for buff in self._id2buff.keys()):
            logger.warning(
                f"could not detach from all buffers for workspace '{self.id}'."
            )
        self._id2buff.clear()

    def __hash__(self) -> int:
        # so we can use these as dict keys!
        return hash(self.id)

    def all_buffers(self) -> list[VirtualBuffer]:
        return list(self._id2buff.values())

    def buff_by_id(self, id: str) -> Optional[VirtualBuffer]:
        return self._id2buff.get(id)

    def install_buffer(self, buff: codemp.BufferController) -> VirtualBuffer:
        logger.debug(f"installing buffer {buff.name()}")

        view = self.window.new_file()
        vbuff = VirtualBuffer(buff, view, self.rootdir)
        self._id2buff[vbuff.id] = vbuff

        return vbuff

    def uninstall_buffer(self, vbuff: VirtualBuffer):
        del self._id2buff[vbuff.id]
        self.codemp.detach(vbuff.id)

    def send_cursor(self, id: str, start: Tuple[int, int], end: Tuple[int, int]):
        # we can safely ignore the promise, we don't really care if everything
        # is ok for now with the cursor.
        self.curctl.send(id, start, end)
