from __future__ import annotations
from typing import Optional, TYPE_CHECKING
if TYPE_CHECKING:
    from .workspace import WorkspaceManager
    import codemp

import sublime
import os
import logging
import threading

from codemp import TextChange
from .. import globals as g
from ..utils import populate_view
from ..utils import get_contents
from ..utils import safe_listener_attach
from ..utils import safe_listener_detach
from ..utils import bidict

logger = logging.getLogger(__name__)

def bind_callback(v: sublime.View):
    # we need this lock to prevent multiple instance of try_recv() to spin up
    # which would cause out of order insertion of changes.
    multi_tryrecv_lock = threading.Lock()

    def _callback(bufctl: codemp.BufferController):
        def _innercb():
            try:
                # change_id = v.change_id()
                change_id = None
                while buffup := bufctl.try_recv().wait():
                    logger.debug("received remote buffer change!")
                    if buffup is None:
                        break

                    if buffup.change.is_empty():
                        logger.debug("change is empty. skipping.")
                        continue

                    # In case a change arrives to a background buffer, just apply it.
                    # We are not listening on it. Otherwise, interrupt the listening
                    # to avoid echoing back the change just received.
                    if v == sublime.active_window().active_view():
                        v.settings()[g.CODEMP_IGNORE_NEXT_TEXT_CHANGE] = True
                    # we need to go through a sublime text command, since the method,
                    # view.replace needs an edit token, that is obtained only when calling
                    # a textcommand associated with a view.

                    change = buffup.change
                    v.run_command(
                        "codemp_replace_text",
                        {
                            "start": change.start_idx,
                            "end": change.end_idx,
                            "content": change.content,
                            "change_id": change_id,
                        },  # pyright: ignore
                    )

                    bufctl.ack(buffup.version)
            except Exception as e:
                raise e
            finally:
                logger.debug("releasing lock")
                multi_tryrecv_lock.release()

        if multi_tryrecv_lock.acquire(blocking=False):
            logger.debug("acquiring lock")
            sublime.set_timeout(_innercb)
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
        self.view.close()
        self.handle.clear_callback()

    def __hash__(self):
        return hash(self.id)

    def send_change(self, changes):
        # we do not do any index checking, and trust sublime with providing the correct
        # sequential indexing, assuming the changes are applied in the order they are received.
        for change in changes:
            region = sublime.Region(change.a.pt, change.b.pt)
            # logger.debug(
            #     "sending txt change: Reg({} {}) -> '{}'".format(
            #         region.begin(), region.end(), change.str
            #     )
            # )

            # we must block and wait the send request to make sure the change went through ok
            self.handle.send(TextChange(start=region.begin(), end=region.end(), content=change.str))

    def sync(self, text_listener):
        promise = self.handle.content()
        def _():
            current_contents = get_contents(self.view)
            content = promise.wait()
            if content == current_contents:
                return

            safe_listener_detach(text_listener)
            populate_view(self.view, content)
            safe_listener_attach(text_listener, self.view.buffer())
            sublime.status_message("Syncd contents.")
        sublime.set_timeout_async(_)

class BufferRegistry():
    def __init__(self):
        self._buffers: bidict[BufferManager, WorkspaceManager] = bidict()

    def __contains__(self, item: str):
        try: self.lookupId(item)
        except KeyError: return False
        return True

    def hasactive(self):
        return len(self._buffers.keys()) > 0

    def lookup(self, ws: Optional[WorkspaceManager] = None) -> list[BufferManager]:
        if not ws:
            return list(self._buffers.keys())
        bfs = self._buffers.inverse.get(ws)
        return bfs if bfs else []

    def lookupParent(self, bf: BufferManager | str) -> WorkspaceManager:
        if isinstance(bf, str):
            bf = self.lookupId(bf)
        return self._buffers[bf]

    def lookupId(self, bid: str) -> BufferManager:
        bfm = next((bf for bf in self._buffers if bf.id == bid), None)
        if not bfm: raise KeyError
        return bfm

    def register(self, bhandle: codemp.BufferController, wsm: WorkspaceManager):
        bid = bhandle.path()
    
        win = sublime.active_window()
        newfileflags = sublime.NewFileFlags.TRANSIENT \
            | sublime.NewFileFlags.ADD_TO_SELECTION \
            | sublime.NewFileFlags.FORCE_CLONE
        view = win.new_file(newfileflags)


        view.set_scratch(True)
        view.set_name(os.path.basename(bid))
        syntax = sublime.find_syntax_for_file(bid)
        if syntax:
            view.assign_syntax(syntax)

        view.settings().set(g.CODEMP_VIEW_TAG, True)
        view.settings().set(g.CODEMP_BUFFER_ID, bid)
        view.set_status(g.SUBLIME_STATUS_ID, "[Codemp]")

        tmpfile = "DISABLE"
        bfm = BufferManager(bhandle, view, tmpfile)
        self._buffers[bfm] = wsm

        return bfm

    def remove(self, bf: BufferManager | str):
        if isinstance(bf, str):
            bf = self.lookupId(bf)

        del self._buffers[bf]


buffers = BufferRegistry()




