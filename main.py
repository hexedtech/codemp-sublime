# pyright: reportIncompatibleMethodOverride=false
import sublime
import sublime_plugin
import logging

from lib import codemp
from .plugin.utils import safe_listener_detach
from .plugin.core.session import session
from .plugin.core.registry import workspaces
from .plugin.core.registry import buffers

from .plugin.commands.client import CodempConnectCommand
from .plugin.commands.client import CodempDisconnectCommand
from .plugin.commands.client import CodempCreateWorkspaceCommand
from .plugin.commands.client import CodempDeleteWorkspaceCommand
from .plugin.commands.client import CodempJoinWorkspaceCommand
from .plugin.commands.client import CodempLeaveWorkspaceCommand
from .plugin.commands.client import CodempInviteToWorkspaceCommand

from .plugin.commands.workspace import CodempCreateBufferCommand
from .plugin.commands.workspace import CodempDeleteBufferCommand
from .plugin.commands.workspace import CodempJoinBufferCommand
from .plugin.commands.workspace import CodempLeaveBufferCommand

LOG_LEVEL = logging.DEBUG
handler = logging.StreamHandler()
handler.setFormatter(
    logging.Formatter(
        fmt="<{thread}/{threadName}> {levelname} [{name} :: {funcName}] {message}",
        style="{",
    )
)
package_logger = logging.getLogger(__package__)
package_logger.setLevel(LOG_LEVEL)
package_logger.propagate = False
logger = logging.getLogger(__name__)

# Initialisation and Deinitialisation
##############################################################################
def plugin_loaded():
    package_logger.addHandler(handler)
    logger.debug("plugin loaded")

def plugin_unloaded():
    logger.debug("unloading")
    safe_listener_detach(TEXT_LISTENER)
    package_logger.removeHandler(handler)


def kill_all():
    for ws in workspaces.lookup():
        session.client.leave_workspace(ws.id)
        workspaces.remove(ws)

    session.stop()


class CodempReplaceTextCommand(sublime_plugin.TextCommand):
    def run(self, edit, start, end, content, change_id):
        # we modify the region to account for any change that happened in the mean time
        region = self.view.transform_region_from(sublime.Region(start, end), change_id)
        self.view.replace(edit, region, content)


class EventListener(sublime_plugin.EventListener):
    def is_enabled(self):
        return session.is_active()

    def on_exit(self):
        kill_all()
        # client.disconnect()
        # if client.driver is not None:
        #     client.driver.stop()

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





# Proxy Commands ( NOT USED, left just in case we need it again. )
#############################################################################
# class ProxyCodempShareCommand(sublime_plugin.WindowCommand):
#   # on_window_command, does not trigger when called from the command palette
#   # See: https://github.com/sublimehq/sublime_text/issues/2234
#   def run(self, **kwargs):
#       self.window.run_command("codemp_share", kwargs)
#
#   def input(self, args):
#       if 'sublime_buffer' not in args:
#           return SublimeBufferPathInputHandler()
#
#   def input_description(self):
#       return 'Share Buffer:'
