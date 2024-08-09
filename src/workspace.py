from __future__ import annotations

import sublime
import shutil
import tempfile
import logging
from asyncio import CancelledError

from codemp import Workspace

from Codemp.src import globals as g
from Codemp.src.buffers import VirtualBuffer
from Codemp.src.task_manager import rt
from Codemp.src.utils import rowcol_to_region

logger = logging.getLogger(__name__)


# A virtual workspace is a bridge class that aims to translate
# events that happen to the codemp workspaces into sublime actions
class VirtualWorkspace:
    def __init__(self, handle: Workspace):
        self.handle = handle
        self.id = self.handle.id()
        self.sublime_window = sublime.active_window()
        self.curctl = handle.cursor()
        self.materialized = False
        self.isactive = False

        # mapping remote ids -> local ids
        self.id_map: dict[str, int] = {}
        self.active_Buffer: dict[int, VirtualBuffer] = {}  # local_id -> VBuff

    def cleanup(self):
        self.deactivate()

        # the worskpace only cares about closing the various open views on its Buffer.
        # the event listener calls the cleanup code for each buffer independently on its own.
        for vbuff in self.active_Buffer.values():
            vbuff.view.close()

        self.active_Buffer = {}  # drop all Buffer, let them be garbace collected (hopefully)

        if not self.materialized:
            return  # nothing to delete

        d: dict = self.sublime_window.project_data()  # pyright: ignore
        newf = list(
            filter(
                lambda f: f.get("name", "") != f"{g.WORKSPACE_FOLDER_PREFIX}{self.id}",
                d["folders"],
            )
        )
        d["folders"] = newf
        self.sublime_window.set_project_data(d)
        logger.info(f"cleaning up virtual workspace '{self.id}'")
        shutil.rmtree(self.rootdir, ignore_errors=True)

        self.curctl.stop()

        s = self.sublime_window.settings()
        del s[g.CODEMP_WINDOW_TAG]
        del s[g.CODEMP_WINDOW_WORKSPACES]

        self.materialized = False

    def materialize(self):
        # attach the workspace to the editor, tagging windows and populating
        # virtual file systems
        if self.materialized:
            return  # no op, we already are in the editor

        # initialise the virtual filesystem
        tmpdir = tempfile.mkdtemp(prefix="codemp_")
        logging.debug("setting up virtual fs for workspace in: {} ".format(tmpdir))
        self.rootdir = tmpdir

        # and add a new "project folder"
        proj_data: dict = self.sublime_window.project_data()  # pyright: ignore
        if proj_data is None:
            proj_data = {"folders": []}

        proj_data["folders"].append(
            {"name": f"{g.WORKSPACE_FOLDER_PREFIX}{self.id}", "path": self.rootdir}
        )
        self.sublime_window.set_project_data(proj_data)

        s: dict = self.sublime_window.settings()  # pyright: ignore
        if s.get(g.CODEMP_WINDOW_TAG, False):
            s[g.CODEMP_WINDOW_WORKSPACES].append(self.id)
        else:
            s[g.CODEMP_WINDOW_TAG] = True
            s[g.CODEMP_WINDOW_WORKSPACES] = [self.id]

        self.materialized = True

    def activate(self):
        rt.dispatch(
            self.move_cursor_task(),
            f"{g.CURCTL_TASK_PREFIX}-{self.id}",
        )
        self.isactive = True

    def deactivate(self):
        if self.isactive:
            rt.stop_task(f"{g.CURCTL_TASK_PREFIX}-{self.id}")

        self.isactive = False

    def add_buffer(self, remote_id: str, vbuff: VirtualBuffer):
        self.id_map[remote_id] = vbuff.view.buffer_id()
        self.active_Buffer[vbuff.view.buffer_id()] = vbuff

    def get_by_local(self, local_id: int) -> VirtualBuffer | None:
        return self.active_Buffer.get(local_id)

    def get_by_remote(self, remote_id: str) -> VirtualBuffer | None:
        local_id = self.id_map.get(remote_id)
        if local_id is None:
            return

        vbuff = self.active_Buffer.get(local_id)
        if vbuff is None:
            logging.warning(
                "a local-remote buffer id pair was found but \
                not the matching virtual buffer."
            )
            return

        return vbuff

    # A workspace has some Buffer inside of it (filetree)
    # some of those you are already attached to (Buffer_by_name)
    # If already attached to it return the same alredy existing bufferctl
    # if existing but not attached (attach)
    # if not existing ask for creation (create + attach)
    async def attach(self, id: str):
        if id is None:
            return

        attached_Buffer = self.handle.buffer_by_name(id)
        if attached_Buffer is not None:
            return self.get_by_remote(id)

        await self.handle.fetch_buffers()
        existing_Buffer = self.handle.filetree()
        if id not in existing_Buffer:
            create = sublime.ok_cancel_dialog(
                "There is no buffer named '{id}' in the workspace.\n\
                Do you want to create it?",
                ok_title="yes",
                title="Create Buffer?",
            )
            if create:
                try:
                    await self.handle.create(id)
                except Exception as e:
                    logging.error(f"could not create buffer:\n\n {e}", True)
                    return
            else:
                return

        # now either we created it or it exists already
        try:
            buff_ctl = await self.handle.attach(id)
        except Exception as e:
            logging.error(f"error when attaching to buffer '{id}':\n\n {e}", True)
            return

        vbuff = VirtualBuffer(self.id, self.rootdir, id, buff_ctl)
        self.add_buffer(id, vbuff)

        # TODO! if the view is already active calling focus_view() will not trigger the on_activate
        self.sublime_window.focus_view(vbuff.view)

    def detach(self, id: str):
        if id is None:
            return

        attached_Buffer = self.handle.buffer_by_name(id)
        if attached_Buffer is None:
            logging.warning(f"You are not attached to the buffer '{id}'", True)
            return

        self.handle.detach(id)

    async def delete(self, id: str):
        if id is None:
            return

        # delete a non existent buffer
        await self.handle.fetch_buffers()
        existing_Buffer = self.handle.filetree()
        if id not in existing_Buffer:
            logging.info(f"The buffer '{id}' does not exists.", True)
            return
        # delete a buffer that exists but you are not attached to
        attached_Buffer = self.handle.buffer_by_name(id)
        if attached_Buffer is None:
            delete = sublime.ok_cancel_dialog(
                "Confirm you want to delete the buffer '{id}'",
                ok_title="delete",
                title="Delete Buffer?",
            )
            if delete:
                try:
                    await self.handle.delete(id)
                except Exception as e:
                    logging.error(
                        f"error when deleting the buffer '{id}':\n\n {e}", True
                    )
                    return
            else:
                return

        # delete buffer that you are attached to
        delete = sublime.ok_cancel_dialog(
            "Confirm you want to delete the buffer '{id}'.\n\
            You will be disconnected from it.",
            ok_title="delete",
            title="Delete Buffer?",
        )
        if delete:
            self.detach(id)
            try:
                await self.handle.delete(id)
            except Exception as e:
                logging.error(f"error when deleting the buffer '{id}':\n\n {e}", True)
                return

    async def move_cursor_task(self):
        logger.debug(f"spinning up cursor worker for workspace '{self.id}'...")
        try:
            while cursor_event := await self.curctl.recv():
                vbuff = self.get_by_remote(cursor_event.buffer)

                if vbuff is None:
                    continue

                reg = rowcol_to_region(vbuff.view, cursor_event.start, cursor_event.end)
                reg_flags = sublime.RegionFlags.DRAW_EMPTY  # show cursors.

                user_hash = hash(cursor_event.user)
                vbuff.view.add_regions(
                    f"{g.SUBLIME_REGIONS_PREFIX}-{user_hash}",
                    [reg],
                    flags=reg_flags,
                    scope=g.REGIONS_COLORS[user_hash % len(g.REGIONS_COLORS)],
                    annotations=[cursor_event.user],
                    annotation_color=g.PALETTE[user_hash % len(g.PALETTE)],
                )

        except CancelledError:
            logger.debug(f"cursor worker for '{self.id}' stopped...")
            raise
        except Exception as e:
            logger.error(f"cursor worker '{self.id}' crashed:\n{e}")
            raise
