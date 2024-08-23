import sublime
import os
import logging

import codemp
from Codemp.src import globals as g

logger = logging.getLogger(__name__)


# This class is used as an abstraction between the local buffers (sublime side) and the
# remote buffers (codemp side), to handle the syncronicity.
# This class is mainly manipulated by a VirtualWorkspace, that manages its buffers
# using this abstract class
class VirtualBuffer:
    def __init__(
        self,
        buffctl: codemp.BufferController,
        view: sublime.View,  # noqa: F821 # type: ignore
    ):
        self.buffctl = buffctl
        self.view = view
        self.id = self.buffctl.name()

    def __hash__(self) -> int:
        return hash(self.id)

    def cleanup(self):
        self.uninstall()
        self.buffctl.stop()

    def install(self, rootdir):
        if self.installed:
            return

        self.tmpfile = os.path.join(rootdir, self.id)
        open(self.tmpfile, "a").close()

        self.view.set_scratch(True)
        self.view.set_name(self.id)
        self.view.retarget(self.tmpfile)

        s = self.view.settings()
        self.view.set_status(g.SUBLIME_STATUS_ID, "[Codemp]")
        s[g.CODEMP_BUFFER_TAG] = True

        self.__activate()

        self.installed = True

    def uninstall(self):
        if not self.installed:
            return

        self.__deactivate()

        os.remove(self.tmpfile)

        s = self.view.settings()
        del s[g.CODEMP_BUFFER_TAG]
        self.view.erase_status(g.SUBLIME_STATUS_ID)

        self.installed = False

    def __activate(self):
        logger.info(f"registering a callback for buffer: {self.id}")
        self.buffctl.callback(self.__apply_bufferchange_cb)
        self.isactive = True

    def __deactivate(self):
        logger.info(f"clearing a callback for buffer: {self.id}")
        self.buffctl.clear_callback()
        self.isactive = False

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

            # we must block and wait the send request to make sure the change went through ok
            self.buffctl.send(region.begin(), region.end(), change.str).wait()

    def __apply_bufferchange_cb(self, bufctl: codemp.BufferController):
        def get_change_and_apply():
            change_id = self.view.change_id()
            while change := bufctl.try_recv().wait():
                if change is None:
                    break

                if change.is_empty():
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
                        "start": change.start,
                        "end": change.end,
                        "content": change.content,
                        "change_id": change_id,
                    },  # pyright: ignore
                )

        sublime.set_timeout(get_change_and_apply)
