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

        # mapping remote ids -> local ids
        self.__buff2view: bidict[VirtualBuffer, sublime.View] = bidict()
        self.__id2buff: dict[str, VirtualBuffer] = {}
        # self.id_map: dict[str, int] = {}
        # self.active_buffers: dict[int, VirtualBuffer] = {}  # local_id -> VBuff

    def __hash__(self) -> int:
        # so we can use these as dict keys!
        return hash(self.id)

    def sync(self):
        # check that the state we have here is the same as the one codemp has internally!
        # if not get up to speed!
        self.codemp.fetch_buffers().wait()
        attached_buffers = self.codemp.buffer_list()
        all(id in self.__id2buff for id in attached_buffers)
        # TODO!

    def valid_bufffer(self, buff: VirtualBuffer | str):
        if isinstance(buff, str):
            return self.buff_by_id(buff) is not None

        return buff in self.__buff2view

    def all_buffers(self) -> list[VirtualBuffer]:
        return list(self.__buff2view.keys())

    def buff_by_view(self, view: sublime.View) -> Optional[VirtualBuffer]:
        buff = self.__buff2view.inverse.get(view)
        return buff[0] if buff is not None else None

    def buff_by_id(self, id: str) -> Optional[VirtualBuffer]:
        return self.__id2buff.get(id)

    def all_views(self) -> list[sublime.View]:
        return list(self.__buff2view.inverse.keys())

    def view_by_buffer(self, buffer: VirtualBuffer) -> sublime.View:
        return buffer.view

    def cleanup(self):
        # the worskpace only cares about closing the various open views of its buffers.
        # the event listener calls the cleanup code for each buffer independently on its own
        # upon closure.
        for view in self.all_views():
            view.close()

        self.__buff2view.clear()
        self.__id2buff.clear()

        self.uninstall()
        self.curctl.stop()

    def uninstall(self):
        if not self.installed:
            return

        self.__deactivate()

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

        self.installed = False

    def install(self):
        if self.installed:
            return

        # initialise the virtual filesystem
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

        self.__activate()
        self.installed = True

    def __activate(self):
        self.curctl.callback(self.__move_cursor_callback)
        self.isactive = True

    def __deactivate(self):
        self.curctl.clear_callback()
        self.isactive = False

    def install_buffer(self, buff: codemp.BufferController) -> VirtualBuffer:
        view = self.window.new_file()

        vbuff = VirtualBuffer(buff, view)
        self.__buff2view[vbuff] = view
        self.__id2buff[vbuff.id] = vbuff

        vbuff.install(self.rootdir)

        return vbuff

    def uninstall_buffer(self, vbuff: VirtualBuffer):
        vbuff.cleanup()
        buffview = self.view_by_buffer(vbuff)
        del self.__buff2view[vbuff]
        del self.__id2buff[vbuff.id]
        buffview.close()

    # def detach(self, id: str):
    #     attached_Buffer = self.codemp.buffer_by_name(id)
    #     if attached_Buffer is None:
    #         sublime.error_message(f"You are not attached to the buffer '{id}'")
    #         logging.warning(f"You are not attached to the buffer '{id}'")
    #         return

    #     self.codemp.detach(id)

    # def delete(self, id: str):
    #     self.codemp.fetch_buffers()
    #     existing_Buffer = self.codemp.filetree(filter=None)
    #     if id not in existing_Buffer:
    #         sublime.error_message(f"The buffer '{id}' does not exists.")
    #         logging.info(f"The buffer '{id}' does not exists.")
    #         return
    #     # delete a buffer that exists but you are not attached to
    #     attached_Buffer = self.codemp.buffer_by_name(id)
    #     if attached_Buffer is None:
    #         delete = sublime.ok_cancel_dialog(
    #             "Confirm you want to delete the buffer '{id}'",
    #             ok_title="delete",
    #             title="Delete Buffer?",
    #         )
    #         if delete:
    #             try:
    #                 self.codemp.delete(id).wait()
    #             except Exception as e:
    #                 logging.error(
    #                     f"error when deleting the buffer '{id}':\n\n {e}", True
    #                 )
    #                 return
    #         else:
    #             return

    #     # delete buffer that you are attached to
    #     delete = sublime.ok_cancel_dialog(
    #         "Confirm you want to delete the buffer '{id}'.\n\
    #         You will be disconnected from it.",
    #         ok_title="delete",
    #         title="Delete Buffer?",
    #     )
    #     if delete:
    #         self.codemp.detach(id)
    #         try:
    #             self.codemp.delete(id).wait()
    #         except Exception as e:
    #             logging.error(f"error when deleting the buffer '{id}':\n\n {e}", True)
    #             return

    def send_cursor(self, id: str, start: Tuple[int, int], end: Tuple[int, int]):
        # we can safely ignore the promise, we don't really care if everything
        # is ok for now with the cursor.
        self.curctl.send(id, start, end)

    def __move_cursor_callback(self, ctl: codemp.CursorController):
        def get_event_and_draw():
            while event := ctl.try_recv().wait():
                if event is None:
                    break

                vbuff = self.buff_by_id(event.buffer)
                if vbuff is None:
                    logger.warning(
                        "received a cursor event for a buffer that wasn't saved internally."
                    )
                    continue

                draw_cursor_region(vbuff.view, event.start, event.end, event.user)

        sublime.set_timeout_async(get_event_and_draw)
