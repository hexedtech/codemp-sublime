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
    def __init__(self, handle: codemp.BufferController, v: sublime.View, filename: str, islocal: bool):
        self.handle: codemp.BufferController = handle
        self.view: sublime.View = v
        self.islocal: bool = islocal
        self.id = self.handle.path()
        self.filename = filename
        self.handle.callback(bind_callback(self.view))

        self.view.settings().set(g.CODEMP_VIEW_TAG, True)
        self.view.settings().set(g.CODEMP_BUFFER_ID, self.id)
        self.view.set_status(g.SUBLIME_STATUS_ID, "[Codemp]")

    def __del__(self):
        logger.debug(f"dropping buffer {self.id}")
        self.handle.clear_callback()
        if self.islocal:
            self.view.settings().erase(g.CODEMP_BUFFER_ID)
            self.view.settings().erase(g.CODEMP_VIEW_TAG)
            self.view.set_status(g.SUBLIME_STATUS_ID, "")
        else:
            self.view.close()

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
            # current_contents = get_contents(self.view)
            content = promise.wait()

            safe_listener_detach(text_listener)
            populate_view(self.view, content)
            safe_listener_attach(text_listener, self.view.buffer())

            sublime.status_message("Syncd contents.")
        sublime.set_timeout_async(_)

    def overwrite(self, text_listener):
        localcontents = get_contents(self.view)
        remotecontents = self.handle.content().wait()
        remotelen = len(remotecontents)
        self.handle.send(
            TextChange(start=0, end=remotelen, content= localcontents)
        )
        self.sync(text_listener)


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

    def register(self, buff: str, wsm: WorkspaceManager, localview: sublime.View | None = None):

        try: buffctl = wsm.handle.attach_buffer(buff).wait()
        except Exception as e:
            logger.error(f"error when attaching to buffer '{id}':\n\n {e}")
            sublime.error_message(f"Could not attach to buffer '{buff}'")
            raise e

        win = sublime.active_window()
        if not localview:
            # TODO: what happens if we join a buffer that exists in the project?
            newfileflags = sublime.NewFileFlags.TRANSIENT \
                | sublime.NewFileFlags.ADD_TO_SELECTION \
                | sublime.NewFileFlags.FORCE_CLONE
            view = win.new_file(newfileflags)


            view.set_scratch(True)
            view.set_name(os.path.basename(buff))
            syntax = sublime.find_syntax_for_file(buff)
            if syntax:
                view.assign_syntax(syntax)
        else:
            view = localview

        tmpfile = "DISABLE"
        bfm = BufferManager(buffctl, view, tmpfile, islocal = localview is not None)
        self._buffers[bfm] = wsm

        return bfm

    def remove(self, bf: BufferManager | str):
        if isinstance(bf, str):
            bf = self.lookupId(bf)
        ws = self.lookupParent(bf)

        del self._buffers[bf]

        bf = bf.id
        if not ws.handle.detach_buffer(bf):
            logger.error(f"could not leave the buffer {bf}.")
        else:
            logger.debug(f"successfully detached from {bf}.")


buffers = BufferRegistry()




