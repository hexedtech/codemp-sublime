from __future__ import annotations

import sublime
import os
import logging

from . import globals as g
from .utils import populate_view, safe_listener_attach, safe_listener_detach
import codemp

logger = logging.getLogger(__name__)

def make_bufferchange_cb(buff: VirtualBuffer):
    def __callback(bufctl: codemp.BufferController):
        def _():
            change_id = buff.view.change_id()
            while change := bufctl.try_recv().wait():
                logger.debug("received remote buffer change!")
                if change is None:
                    break

                if change.is_empty():
                    logger.debug("change is empty. skipping.")
                    continue

                # In case a change arrives to a background buffer, just apply it.
                # We are not listening on it. Otherwise, interrupt the listening
                # to avoid echoing back the change just received.
                if buff.view.id() == g.ACTIVE_CODEMP_VIEW:
                    buff.view.settings()[g.CODEMP_IGNORE_NEXT_TEXT_CHANGE] = True

                # we need to go through a sublime text command, since the method,
                # view.replace needs an edit token, that is obtained only when calling
                # a textcommand associated with a view.
                buff.view.run_command(
                    "codemp_replace_text",
                    {
                        "start": change.start,
                        "end": change.end,
                        "content": change.content,
                        "change_id": change_id,
                    },  # pyright: ignore
                )

        sublime.set_timeout(_)
    return __callback


class VirtualBuffer:
    def __init__(
        self,
        buffctl: codemp.BufferController,
        view: sublime.View,
        rootdir: str,
    ):
        self.buffctl = buffctl
        self.view = view
        self.id = self.buffctl.path()

        self.tmpfile = os.path.join(rootdir, self.id)
        open(self.tmpfile, "a").close()

        self.view.set_scratch(True)
        self.view.set_name(self.id)
        self.view.retarget(self.tmpfile)

        self.view.settings().set(g.CODEMP_BUFFER_TAG, True)
        self.view.set_status(g.SUBLIME_STATUS_ID, "[Codemp]")

        logger.info(f"registering a callback for buffer: {self.id}")
        self.buffctl.callback(make_bufferchange_cb(self))
        self.isactive = True

    def __del__(self):
        logger.debug("__del__ buffer called.")

    def __hash__(self) -> int:
        return hash(self.id)

    def uninstall(self):
        logger.info(f"clearing a callback for buffer: {self.id}")
        self.buffctl.clear_callback()
        self.buffctl.stop()
        self.isactive = False

        os.remove(self.tmpfile)

        def onclose(did_close):
            if did_close:
                logger.info(f"'{self.id}' closed successfully")
            else:
                logger.info(f"failed to close the view for '{self.id}'")

        self.view.close(onclose)

    def sync(self, text_listener):
        promise = self.buffctl.content()

        def _():
            content = promise.wait()
            safe_listener_detach(text_listener)
            populate_view(self.view, content)
            safe_listener_attach(text_listener, self.view.buffer())

        sublime.set_timeout_async(_)

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
