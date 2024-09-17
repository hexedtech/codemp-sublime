import sublime
import sublime_plugin
import logging

from .src.client import client
from .src.utils import safe_listener_attach
from .src.utils import safe_listener_detach
from .src import globals as g

logger = logging.getLogger(__name__)


# Listeners
##############################################################################
class EventListener(sublime_plugin.EventListener):
    def is_enabled(self):
        return client.codemp is not None

    def on_exit(self):
        client.disconnect()
        if client.driver is not None:
            client.driver.stop()

    def on_pre_close_window(self, window):
        assert client.codemp is not None

        for vws in client.all_workspaces(window):
            client.codemp.leave_workspace(vws.id)
            client.uninstall_workspace(vws)

    def on_text_command(self, view, command_name, args):
        if command_name == "codemp_replace_text":
            logger.info("got a codemp_replace_text command!")

    def on_post_text_command(self, view, command_name, args):
        if command_name == "codemp_replace_text":
            logger.info("got a codemp_replace_text command!")


class CodempClientViewEventListener(sublime_plugin.ViewEventListener):
    @classmethod
    def is_applicable(cls, settings):
        return settings.get(g.CODEMP_BUFFER_TAG) is not None

    @classmethod
    def applies_to_primary_view_only(cls):
        return False

    def on_selection_modified_async(self):
        region = self.view.sel()[0]
        start = self.view.rowcol(region.begin())
        end = self.view.rowcol(region.end())

        vws = client.workspace_from_view(self.view)
        vbuff = client.buffer_from_view(self.view)
        if vws is None or vbuff is None:
            logger.error("we couldn't find the matching buffer or workspace!")
            return

        logger.debug(f"selection modified! {vws.id}, {vbuff.id} - {start}, {end}")
        vws.send_cursor(vbuff.id, start, end)

    def on_activated(self):
        global TEXT_LISTENER
        logger.debug(f"'{self.view}' view activated!")
        safe_listener_attach(TEXT_LISTENER, self.view.buffer())  # pyright: ignore

    def on_deactivated(self):
        global TEXT_LISTENER
        logger.debug(f"'{self.view}' view deactivated!")
        safe_listener_detach(TEXT_LISTENER)  # pyright: ignore

    def on_pre_close(self):
        if self.view == sublime.active_window().active_view():
            logger.debug("closing active view")
            global TEXT_LISTENER
            safe_listener_detach(TEXT_LISTENER)  # pyright: ignore

        vws = client.workspace_from_view(self.view)
        vbuff = client.buffer_from_view(self.view)
        if vws is None or vbuff is None:
            logger.debug("no matching workspace or buffer.")
            return

        client.unregister_buffer(vbuff)
        vws.uninstall_buffer(vbuff)

    def on_text_command(self, command_name, args):
        if command_name == "codemp_replace_text":
            logger.info("got a codemp_replace_text command! but in the view listener")

    def on_post_text_command(self, command_name, args):
        if command_name == "codemp_replace_text":
            logger.info("got a codemp_replace_text command! but in the view listener")


class CodempClientTextChangeListener(sublime_plugin.TextChangeListener):
    @classmethod
    def is_applicable(cls, buffer):  # pyright: ignore
        # don't attach this event listener automatically
        # we'll do it by hand with .attach(buffer).
        return False

    def on_text_changed(self, changes):
        s = self.buffer.primary_view().settings()
        if s.get(g.CODEMP_IGNORE_NEXT_TEXT_CHANGE, False):
            logger.debug("Ignoring echoing back the change.")
            s[g.CODEMP_IGNORE_NEXT_TEXT_CHANGE] = False
            return

        vbuff = client.buffer_from_view(self.buffer.primary_view())
        if vbuff is not None:
            logger.debug(f"local buffer change! {vbuff.id}")
            vbuff.send_buffer_change(changes)


TEXT_LISTENER = CodempClientTextChangeListener()
