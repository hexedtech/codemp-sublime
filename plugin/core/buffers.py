from __future__ import annotations
from typing import Optional, TYPE_CHECKING
if TYPE_CHECKING:
    from .workspace import WorkspaceManager
    import codemp

import sublime
import os
import logging

from .. import globals as g
from ..utils import populate_view
from ..utils import safe_listener_attach
from ..utils import safe_listener_detach
from ..utils import bidict

logger = logging.getLogger(__name__)

def bind_callback(v: sublime.View):
    def _callback(bufctl: codemp.BufferController):
        def _():
            change_id = v.change_id()
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
                if v.id() == g.ACTIVE_CODEMP_VIEW:
                    v.settings()[g.CODEMP_IGNORE_NEXT_TEXT_CHANGE] = True

                # we need to go through a sublime text command, since the method,
                # view.replace needs an edit token, that is obtained only when calling
                # a textcommand associated with a view.
                v.run_command(
                    "codemp_replace_text",
                    {
                        "start": change.start,
                        "end": change.end,
                        "content": change.content,
                        "change_id": change_id,
                    },  # pyright: ignore
                )
        sublime.set_timeout(_)
    return _callback

class BufferManager():
    def __init__(self, handle: codemp.BufferController, v: sublime.View, filename: str):
        self.handle: codemp.BufferController = handle
        self.view: sublime.View = v
        self.id = self.handle.path()
        self.filename = filename
        self.handle.callback(bind_callback(self.view))

    def __del__(self):
        logger.debug(f"dropping buffer {self.id}")
        self.handle.clear_callback()
        self.handle.stop()

    def __hash__(self):
        return hash(self.id)

    def send_change(self, changes):
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
            self.handle.send(region.begin(), region.end(), change.str).wait()

    def sync(self, text_listener):
        promise = self.handle.content()
        def _():
            content = promise.wait()
            safe_listener_detach(text_listener)
            populate_view(self.view, content)
            safe_listener_attach(text_listener, self.view.buffer())
        sublime.set_timeout_async(_)

class BufferRegistry():
    def __init__(self):
        self._buffers: bidict[BufferManager, WorkspaceManager] = bidict()

    def lookup(self, ws: Optional[WorkspaceManager] = None) -> list[BufferManager]:
        if not ws:
            return list(self._buffers.keys())
        bf = self._buffers.inverse.get(ws)
        return bf if bf else []

    def lookupId(self, bid: str) -> Optional[BufferManager]:
        return next((bf for bf in self._buffers if bf.id == bid), None)

    def add(self, bhandle: codemp.BufferController, wsm: WorkspaceManager):
        bid = bhandle.path()
        tmpfile = os.path.join(wsm.rootdir, bid)
        open(tmpfile, "a").close()

        win = sublime.active_window()
        view = win.open_file(bid)
        view.set_scratch(True)
        view.retarget(tmpfile)
        view.settings().set(g.CODEMP_VIEW_TAG, True)
        view.settings().set(g.CODEMP_BUFFER_ID, bid)
        view.set_status(g.SUBLIME_STATUS_ID, "[Codemp]")

        bfm = BufferManager(bhandle, view, tmpfile)
        self._buffers[bfm] = wsm

    def remove(self, bf: Optional[BufferManager | str]):
        if isinstance(bf, str):
            bf = self.lookupId(bf)
        if not bf: return

        del self._buffers[bf]
        bf.view.close()

buffers = BufferRegistry()




