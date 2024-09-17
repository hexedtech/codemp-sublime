# pyright: reportIncompatibleMethodOverride=false
import sublime
import sublime_plugin
import logging

from .src.utils import safe_listener_detach
from listeners import TEXT_LISTENER

from client_commands import CodempConnectCommand
from client_commands import CodempDisconnectCommand
from client_commands import CodempCreateWorkspaceCommand
from client_commands import CodempDeleteWorkspaceCommand
from client_commands import CodempJoinWorkspaceCommand
from client_commands import CodempLeaveWorkspaceCommand
from client_commands import CodempInviteToWorkspaceCommand

from workspace_commands import CodempCreateBufferCommand
from workspace_commands import CodempDeleteBufferCommand
from workspace_commands import CodempJoinBufferCommand
from workspace_commands import CodempLeaveBufferCommand

LOG_LEVEL = logging.DEBUG
handler = logging.StreamHandler()
handler.setFormatter(
    logging.Formatter(
        fmt="<{thread}/{threadName}> {levelname} [{name} :: {funcName}] {message}",
        style="{",
    )
)
package_logger = logging.getLogger(__package__)
package_logger.addHandler(handler)
package_logger.setLevel(LOG_LEVEL)
package_logger.propagate = False
logger = logging.getLogger(__name__)


# Initialisation and Deinitialisation
##############################################################################
def plugin_loaded():
    logger.debug("plugin loaded")


def plugin_unloaded():
    logger.debug("unloading")
    safe_listener_detach(TEXT_LISTENER)
    package_logger.removeHandler(handler)
    # client.disconnect()


# Text Change Command
#############################################################################
class CodempReplaceTextCommand(sublime_plugin.TextCommand):
    def run(self, edit, start, end, content, change_id):
        # we modify the region to account for any change that happened in the mean time
        region = self.view.transform_region_from(sublime.Region(start, end), change_id)
        self.view.replace(edit, region, content)


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
