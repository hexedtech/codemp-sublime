import sublime
import os
import logging
from asyncio import CancelledError

from codemp import BufferController
from Codemp.src import globals as g
from Codemp.src.task_manager import tm

logger = logging.getLogger(__name__)


# This class is used as an abstraction between the local buffers (sublime side) and the
# remote buffers (codemp side), to handle the syncronicity.
# This class is mainly manipulated by a VirtualWorkspace, that manages its buffers
# using this abstract class
class VirtualBuffer:
    def __init__(
        self,
        workspace_id: str,
        workspace_rootdir: str,
        remote_id: str,
        buffctl: BufferController,
    ):
        self.view = sublime.active_window().new_file()
        self.codemp_id = remote_id
        self.sublime_id = self.view.buffer_id()
        self.workspace_id = workspace_id
        self.workspace_rootdir = workspace_rootdir
        self.buffctl = buffctl

        self.tmpfile = os.path.join(workspace_rootdir, self.codemp_id)

        self.view.set_name(self.codemp_id)
        open(self.tmpfile, "a").close()
        self.view.retarget(self.tmpfile)
        self.view.set_scratch(True)

        tm.dispatch(
            self.apply_bufferchange_task(),
            f"{g.BUFFCTL_TASK_PREFIX}-{self.codemp_id}",
        )

        # mark the view as a codemp view
        s = self.view.settings()
        self.view.set_status(g.SUBLIME_STATUS_ID, "[Codemp]")
        s[g.CODEMP_BUFFER_TAG] = True
        s[g.CODEMP_REMOTE_ID] = self.codemp_id
        s[g.CODEMP_WORKSPACE_ID] = self.workspace_id

    def cleanup(self):
        os.remove(self.tmpfile)
        # cleanup views
        s = self.view.settings()
        del s[g.CODEMP_BUFFER_TAG]
        del s[g.CODEMP_REMOTE_ID]
        del s[g.CODEMP_WORKSPACE_ID]
        self.view.erase_status(g.SUBLIME_STATUS_ID)

        tm.stop(f"{g.BUFFCTL_TASK_PREFIX}-{self.codemp_id}")
        logger.info(f"cleaning up virtual buffer '{self.codemp_id}'")

    async def apply_bufferchange_task(self):
        logger.debug(f"spinning up '{self.codemp_id}' buffer worker...")
        try:
            while text_change := await self.buffctl.recv():
                change_id = self.view.change_id()
                if text_change.is_empty():
                    logger.debug("change is empty. skipping.")
                    continue
                # In case a change arrives to a background buffer, just apply it.
                # We are not listening on it. Otherwise, interrupt the listening
                # to avoid echoing back the change just received.
                if self.view.id() == g.ACTIVE_CODEMP_VIEW:
                    self.view.settings()[g.CODEMP_IGNORE_NEXT_TEXT_CHANGE] = True

                # we need to go through a sublime text command, since the method,
                # view.replace needs an edit token, that is obtained only when calling
                # a textcommand associated with a view.
                self.view.run_command(
                    "codemp_replace_text",
                    {
                        "start": text_change.start,
                        "end": text_change.end,
                        "content": text_change.content,
                        "change_id": change_id,
                    },  # pyright: ignore
                )

        except CancelledError:
            logger.debug(f"'{self.codemp_id}' buffer worker stopped...")
            raise
        except Exception as e:
            logger.error(f"buffer worker '{self.codemp_id}' crashed:\n{e}")
            raise

    def send_buffer_change(self, changes):
        # we do not do any index checking, and trust sublime with providing the correct
        # sequential indexing, assuming the changes are applied in the order they are received.
        for change in changes:
            region = sublime.Region(change.a.pt, change.b.pt)
            logger.debug(
                "sending txt change: Reg({} {}) -> '{}'".format(
                    region.begin(), region.end(), change.str
                )
            )
            self.buffctl.send(region.begin(), region.end(), change.str)

    def send_cursor(self, vws):  # pyright: ignore  # noqa: F821
        # TODO: only the last placed cursor/selection.
        # status_log(f"sending cursor position in workspace: {vbuff.workspace.id}")
        region = self.view.sel()[0]
        start = self.view.rowcol(region.begin())  # only counts UTF8 chars
        end = self.view.rowcol(region.end())

        vws.curctl.send(self.codemp_id, start, end)
