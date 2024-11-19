import sublime
import sublime_plugin
import logging

from .core.buffers import buffers
from . import globals as g

logger = logging.getLogger(__name__)

class CodempClientTextChangeListener(sublime_plugin.TextChangeListener):
    @classmethod
    def is_applicable(cls, _):  # pyright: ignore
        # don't attach this event listener automatically
        # we'll do it by hand with .attach(buffer).
        return False

    def on_text_changed(self, changes):
        s = self.buffer.primary_view().settings()
        if s.get(g.CODEMP_IGNORE_NEXT_TEXT_CHANGE, False):
            logger.debug("Ignoring echoing back the change.")
            s[g.CODEMP_IGNORE_NEXT_TEXT_CHANGE] = False
            return

        bid = str(s.get(g.CODEMP_BUFFER_ID))
        try:
            vbuff = buffers.lookupId(bid)
            logger.debug(f"local buffer change! {vbuff.id}")
            vbuff.send_change(changes)
        except KeyError:
            logger.error(f"could not find registered buffer with id {bid}")
            pass

TEXT_LISTENER = CodempClientTextChangeListener()