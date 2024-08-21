# pyright: reportIncompatibleMethodOverride=false

import sublime
import sublime_plugin
import logging
import random

# from Codemp.src.task_manager import rt
from Codemp.src.client import client
from Codemp.src.utils import safe_listener_detach
from Codemp.src.utils import safe_listener_attach
from Codemp.src import globals as g
from codemp import register_logger

LOG_LEVEL = logging.DEBUG
handler = logging.StreamHandler()
handler.setFormatter(
    logging.Formatter(
        fmt="<{thread}/{threadName}>[codemp] [{name} :: {funcName}] {levelname}: {message}",
        style="{",
    )
)
package_logger = logging.getLogger(__package__)
package_logger.addHandler(handler)
package_logger.setLevel(LOG_LEVEL)
package_logger.propagate = False

logger = logging.getLogger(__name__)

# returns false if logger already exists
register_logger(lambda msg: logger.log(logger.level, msg), False)

TEXT_LISTENER = None


# Initialisation and Deinitialisation
##############################################################################
def plugin_loaded():
    global TEXT_LISTENER
    TEXT_LISTENER = CodempClientTextChangeListener()
    logger.debug("plugin loaded")


def plugin_unloaded():
    logger.debug("unloading")
    global TEXT_LISTENER

    if TEXT_LISTENER is not None:
        safe_listener_detach(TEXT_LISTENER)

    package_logger.removeHandler(handler)
    client.disconnect()
    # rt.stop_loop()


# Listeners
##############################################################################
class EventListener(sublime_plugin.EventListener):
    def on_exit(self):
        client.disconnect()

    def on_pre_close_window(self, window):
        if client.active_workspace is None:
            return  # nothing to do

        # deactivate all workspaces
        client.make_active(None)

        s = window.settings()
        if not s.get(g.CODEMP_WINDOW_TAG, False):
            return

        for wsid in s[g.CODEMP_WINDOW_WORKSPACES]:
            ws = client[wsid]
            if ws is None:
                logger.warning(
                    "a tag on the window was found but not a matching workspace."
                )
                continue

            ws.cleanup()
            del client.workspaces[wsid]


class CodempClientViewEventListener(sublime_plugin.ViewEventListener):
    @classmethod
    def is_applicable(cls, settings):
        return settings.get(g.CODEMP_BUFFER_TAG, False)

    @classmethod
    def applies_to_primary_view_only(cls):
        return False

    def on_selection_modified_async(self):
        ws = client.get_workspace(self.view)
        if ws is None:
            return

        vbuff = ws.get_by_local(self.view.buffer_id())
        if vbuff is not None:
            vbuff.send_cursor(ws)

    def on_activated(self):
        # sublime has no proper way to check if a view gained or lost input focus outside of this
        # callback (i know right?), so we have to manually keep track of which view has the focus
        g.ACTIVE_CODEMP_VIEW = self.view.id()
        # print("view {} activated".format(self.view.id()))
        global TEXT_LISTENER
        safe_listener_attach(TEXT_LISTENER, self.view.buffer())  # pyright: ignore

    def on_deactivated(self):
        g.ACTIVE_CODEMP_VIEW = None
        # print("view {} deactivated".format(self.view.id()))
        global TEXT_LISTENER
        safe_listener_detach(TEXT_LISTENER)  # pyright: ignore

    def on_pre_close(self):
        global TEXT_LISTENER
        if self.view.id() == g.ACTIVE_CODEMP_VIEW:
            safe_listener_detach(TEXT_LISTENER)  # pyright: ignore

        ws = client.get_workspace(self.view)
        if ws is None:
            return

        vbuff = ws.get_by_local(self.view.buffer_id())
        if vbuff is not None:
            vbuff.cleanup()


class CodempClientTextChangeListener(sublime_plugin.TextChangeListener):
    @classmethod
    def is_applicable(cls, buffer):
        # don't attach this event listener automatically
        # we'll do it by hand with .attach(buffer).
        return False

    # blocking :D
    def on_text_changed(self, changes):
        s = self.buffer.primary_view().settings()
        if s.get(g.CODEMP_IGNORE_NEXT_TEXT_CHANGE, None):
            logger.debug("Ignoring echoing back the change.")
            s[g.CODEMP_IGNORE_NEXT_TEXT_CHANGE] = False
            return

        vbuff = client.get_buffer(self.buffer.primary_view())
        if vbuff is not None:
            rt.dispatch(vbuff.send_buffer_change(changes))


# Commands:
#   codemp_connect:         connect to a server.
#   codemp_join:            shortcut command if you already know both workspace id
#                           and buffer id
#   codemp_join_workspace:  joins a specific workspace, without joining also a buffer
#   codemp_join_buffer:     joins a specific buffer within the current active workspace


#   codemp_share:           ??? todo!()
#   codemp_disconnect:      manually call the disconnection, triggering the cleanup and dropping
#                           the connection
#
# Internal commands:
#   replace_text:       swaps the content of a view with the given text.
#
# Connect Command
#############################################################################
class CodempConnectCommand(sublime_plugin.WindowCommand):
    def run(self, server_host, user_name, password="lmaodefaultpassword"):
        client.connect(server_host, user_name, password)

    def is_enabled(self) -> bool:
        return client.handle is None

    def input(self, args):
        if "server_host" not in args:
            return ConnectServerHost()

    def input_description(self):
        return "Server host:"


class ConnectServerHost(sublime_plugin.TextInputHandler):
    def name(self):
        return "server_host"

    def initial_text(self):
        return "http://127.0.0.1:50051"

    def next_input(self, args):
        if "user_name" not in args:
            return ConnectUserName(args)


class ConnectUserName(sublime_plugin.TextInputHandler):
    def __init__(self, args):
        self.host = args["server_host"]

    def name(self):
        return "user_name"

    def initial_text(self):
        return f"user-{random.random()}"


# Separate the join command into two join workspace and join buffer commands that get called back to back


# Generic Join Command
#############################################################################
class CodempJoinCommand(sublime_plugin.WindowCommand):
    def run(self, workspace_id, buffer_id):
        if workspace_id == "":
            return

        vws = client.workspaces.get(workspace_id)
        if vws is None:
            try:
                vws = client.join_workspace(workspace_id)
            except Exception as e:
                raise e

        if vws is None:
            logger.warning("The client returned a void workspace.")
            return

        vws.materialize()

        if buffer_id == "* Don't Join Any":
            buffer_id = ""

        if buffer_id != "":
            vws.attach(buffer_id)

    def is_enabled(self) -> bool:
        return client.handle is not None

    def input_description(self):
        return "Join:"

    def input(self, args):
        if "workspace_id" not in args:
            return JoinWorkspaceIdList()


class JoinWorkspaceIdList(sublime_plugin.ListInputHandler):
    # To allow for having a selection and choosing non existing workspaces
    # we do a little dance: We pass this list input handler to a TextInputHandler
    # when we select "Create New..." which adds his result to the list of possible
    # workspaces and pop itself off the stack to go back to the list handler.
    def __init__(self):
        self.list = client.active_workspaces()
        self.list.sort()
        self.list.append("* Create New...")
        self.preselected = None

    def name(self):
        return "workspace_id"

    def placeholder(self):
        return "Workspace"

    def list_items(self):
        if self.preselected is not None:
            return (self.list, self.preselected)
        else:
            return self.list

    def next_input(self, args):
        if args["workspace_id"] == "* Create New...":
            return AddListEntryName(self)

        wid = args["workspace_id"]
        if wid != "":
            vws = client.join_workspace(wid)
        else:
            vws = None
        try:
            return ListBufferId(vws)
        except Exception:
            return TextBufferId()


class TextBufferId(sublime_plugin.TextInputHandler):
    def name(self):
        return "buffer_id"


class ListBufferId(sublime_plugin.ListInputHandler):
    def __init__(self, vws):
        self.ws = vws
        self.list = vws.handle.filetree()
        self.list.sort()
        self.list.append("* Create New...")
        self.list.append("* Don't Join Any")
        self.preselected = None

    def name(self):
        return "buffer_id"

    def placeholder(self):
        return "Buffer Id"

    def list_items(self):
        if self.preselected is not None:
            return (self.list, self.preselected)
        else:
            return self.list

    def cancel(self):
        client.leave_workspace(self.ws.id)

    def next_input(self, args):
        if args["buffer_id"] == "* Create New...":
            return AddListEntryName(self)

        if args["buffer_id"] == "* Dont' Join Any":
            return None


class AddListEntryName(sublime_plugin.TextInputHandler):
    def __init__(self, list_handler):
        self.parent = list_handler

    def name(self):
        return None

    def validate(self, text: str) -> bool:
        return not len(text) == 0

    def confirm(self, text: str):
        self.parent.list.pop()  # removes the "Create New..."
        self.parent.list.insert(0, text)
        self.parent.preselected = 0

    def next_input(self, args):
        return sublime_plugin.BackInputHandler()


# Text Change Command
#############################################################################
class CodempReplaceTextCommand(sublime_plugin.TextCommand):
    def run(self, edit, start, end, content, change_id):
        # we modify the region to account for any change that happened in the mean time
        region = self.view.transform_region_from(sublime.Region(start, end), change_id)
        self.view.replace(edit, region, content)


# Share Command
# #############################################################################
# class CodempShareCommand(sublime_plugin.WindowCommand):
#     def run(self, sublime_buffer_path, server_id):
#         sublime_asyncio.dispatch(share_buffer_command(sublime_buffer_path, server_id))

#     def input(self, args):
#         if "sublime_buffer" not in args:
#             return SublimeBufferPathInputHandler()

#     def input_description(self):
#         return "Share Buffer:"


# Disconnect Command
#############################################################################
class CodempDisconnectCommand(sublime_plugin.WindowCommand):
    def is_enabled(self) -> bool:
        if client.handle is not None:
            return True
        else:
            return False

    def run(self):
        client.disconnect()


# Leave Workspace Command
class CodempLeaveWorkspaceCommand(sublime_plugin.WindowCommand):
    def is_enabled(self) -> bool:
        return client.handle is not None and len(client.workspaces.keys()) > 0

    def run(self, id: str):
        client.leave_workspace(id)

    def input(self, args):
        if "id" not in args:
            return LeaveWorkspaceIdList()


class LeaveWorkspaceIdList(sublime_plugin.ListInputHandler):
    def name(self):
        return "id"

    def list_items(self):
        return client.active_workspaces()


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


# NOT NEEDED ANYMORE
# def compress_change_region(changes):
#   # the bounding region of all text changes.
#   txt_a = float("inf")
#   txt_b = 0

#   # the region in the original buffer subjected to the change.
#   reg_a = float("inf")
#   reg_b = 0

#   # we keep track of how much the changes move the indexing of the buffer
#   buffer_shift = 0 # left - + right

#   for change in changes:
#       # the change in characters that the change would bring
#       # len(str) and .len_utf8 are mutually exclusive
#       # len(str) is when we insert new text at a position
#       # .len_utf8 is the length of the deleted/canceled string in the buffer
#       change_delta = len(change.str) - change.len_utf8

#       # the text region is enlarged to the left
#       txt_a = min(txt_a, change.a.pt)

#       # On insertion, change.b.pt == change.a.pt
#       #   If we meet a new insertion further than the current window
#       #   we expand to the right by that change.
#       # On deletion, change.a.pt == change.b.pt - change.len_utf8
#       #   when we delete a selection and it is further than the current window
#       #   we enlarge to the right up until the begin of the deleted region.
#       if change.b.pt > txt_b:
#           txt_b = change.b.pt + change_delta
#       else:
#           # otherwise we just shift the window according to the change
#           txt_b += change_delta

#       # the bounding region enlarged to the left
#       reg_a = min(reg_a, change.a.pt)

#       # In this bit, we want to look at the buffer BEFORE the modifications
#       # but we are working on the buffer modified by all previous changes for each loop
#       # we use buffer_shift to keep track of how the buffer shifts around
#       # to map back to the correct index for each change in the unmodified buffer.
#       if change.b.pt + buffer_shift > reg_b:
#           # we only enlarge if we have changes that exceede on the right the current window
#           reg_b = change.b.pt + buffer_shift

#       # after using the change delta, we archive it for the next iterations
#       # the minus is just for being able to "add" the buffer shift with a +.
#       # since we encode deleted text as negative in the change_delta, but that requires the shift to the
#       # old position to be positive, and viceversa for text insertion.
#       buffer_shift -= change_delta

#       # print("\t[buff change]", change.a.pt, change.str, "(", change.len_utf8,")", change.b.pt)

#   # print("[walking txt]", "[", txt_a, txt_b, "]", txt)
#   # print("[walking reg]", "[", reg_a, reg_b, "]")
#   return reg_a, reg_b
