# pyright: reportIncompatibleMethodOverride=false
import sublime
import sublime_plugin
import logging

import codemp
from .plugin.utils import safe_listener_detach
from .plugin.utils import safe_listener_attach
from .plugin.utils import some
from .plugin.core.session import session
from .plugin.core.workspace import workspaces
from .plugin.core.buffers import buffers
from .plugin.text_listener import TEXT_LISTENER
from .plugin.input_handlers import SimpleListInput
from .plugin import globals as g

from .plugin.quickpanel.qpbrowser import QPServerBrowser
from .plugin.quickpanel.qpbrowser import QPWorkspaceBrowser


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
    version = codemp.version()
    logger.debug("plugin loaded - library version: {}".format(version))

def plugin_unloaded():
    logger.debug("unloading")
    safe_listener_detach(TEXT_LISTENER)
    package_logger.removeHandler(handler)

def kill_all():
    for ws in workspaces.lookup():
        session.client.leave_workspace(ws.id)
        workspaces.remove(ws)

    session.stop()

def vbuff_form_view(view):
    if not view.settings().get(g.CODEMP_VIEW_TAG, False):
        raise ValueError("The view is not a Codemp Buffer.")

    buffid = str(view.settings().get(g.CODEMP_BUFFER_ID))
    vbuff = buffers.lookupId(buffid)

    return vbuff

def objects_from_view(view):

    vbuff = vbuff_form_view(view)
    vws = buffers.lookupParent(vbuff)
    win = workspaces.lookupParent(vws)

    return win, vws, vbuff

class CodempBrowseWorkspaceCommand(sublime_plugin.WindowCommand):
    def is_enabled(self) -> bool:
        return session.is_active()

    def run(self, workspace_id):
        wks = workspaces.lookupId(workspace_id)
        buffers = wks.handle.fetch_buffers()
        QPWorkspaceBrowser(self.window, workspace_id, buffers.wait()).run()

    def input(self, args):
        if "workspace_id" not in args:
            wslist = session.client.active_workspaces()
            return SimpleListInput(
                ("workspace_id", wslist),
            )


class CodempBrowseServerCommand(sublime_plugin.WindowCommand):
    def is_enabled(self) -> bool:
        return session.is_active()

    def run(self):
        wks = session.get_workspaces()
        QPServerBrowser(self.window, session.config.host, wks).run()


class CodempReplaceTextCommand(sublime_plugin.TextCommand):
    def run(self, edit, start, end, content, change_id = None):
        # we modify the region to account for any change that happened in the mean time
        region = sublime.Region(start, end)
        if change_id:
            region = self.view.transform_region_from(sublime.Region(start, end), change_id)
        self.view.replace(edit, region, content)


class CodempSyncBuffer(sublime_plugin.TextCommand):
    def run(self, edit):
        buff = buffers.lookupId(str(self.view.settings().get(g.CODEMP_BUFFER_ID)))
        buff.sync(TEXT_LISTENER)


class EventListener(sublime_plugin.EventListener):
    def is_enabled(self):
        return session.is_active()

    def on_exit(self):
        kill_all()

    def on_pre_close_window(self, window):
        for vws in workspaces.lookup(window):
            sublime.run_command("codemp_leave_workspace", {
                "workspace_id": vws.id
                })

    def on_text_command(self, view, command_name, args):
        if command_name == "codemp_replace_text":
            logger.info("got a codemp_replace_text command!")

    def on_post_text_command(self, view, command_name, args):
        if command_name == "codemp_replace_text":
            logger.info("got a codemp_replace_text command!")


class CodempClientViewEventListener(sublime_plugin.ViewEventListener):
    @classmethod
    def is_applicable(cls, settings):
        return settings.get(g.CODEMP_VIEW_TAG) is not None

    @classmethod
    def applies_to_primary_view_only(cls):
        return False

    def on_selection_modified_async(self):
        region = self.view.sel()[0]
        start = self.view.rowcol(region.begin())
        end = self.view.rowcol(region.end())

        try:
            _, vws, vbuff = objects_from_view(self.view)
        except KeyError:
            logger.error(f"Could not find buffers associated with the view {self.view}.\
                Removing the tag to disable event listener. Reattach.")
            # delete the tag so we disable this event listener on the view
            del self.view.settings()[g.CODEMP_VIEW_TAG]
            return

        vws.send_cursor(vbuff.id, start, end)
        # logger.debug(f"selection modified! {vws.id}, {vbuff.id} - {start}, {end}")

    def on_activated(self):
        logger.debug(f"'{self.view}' view activated!")
        safe_listener_attach(TEXT_LISTENER, self.view.buffer())  # pyright: ignore

    def on_deactivated(self):
        logger.debug(f"'{self.view}' view deactivated!")
        safe_listener_detach(TEXT_LISTENER)  # pyright: ignore

    def on_pre_close(self):
        if self.view == sublime.active_window().active_view():
            logger.debug("closing active view")
            safe_listener_detach(TEXT_LISTENER)  # pyright: ignore
        try:
            bid = str(self.view.settings().get(g.CODEMP_BUFFER_ID))
            vws = buffers.lookupParent(bid)
            some(self.view.window()).run_command(
                "codemp_leave_buffer",
                {"workspace_id": vws.id, "buffer_id": bid})
        except KeyError:
            return

    def on_text_command(self, command_name, args):
        if command_name == "codemp_replace_text":
            logger.info("got a codemp_replace_text command! but in the view listener")

    def on_post_text_command(self, command_name, args):
        if command_name == "codemp_replace_text":
            logger.info("got a codemp_replace_text command! but in the view listener")




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





