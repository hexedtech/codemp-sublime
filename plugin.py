import sublime
import sublime_plugin

from Codemp.src.codemp_client import VirtualClient
from Codemp.src.TaskManager import rt
from Codemp.src.utils import status_log
from Codemp.src.utils import safe_listener_detach
from Codemp.src.utils import get_contents
from Codemp.src.utils import populate_view
from Codemp.src.utils import get_view_from_local_path
import Codemp.src.globals as g

CLIENT = None
TEXT_LISTENER = None


# Initialisation and Deinitialisation
##############################################################################
def plugin_loaded():
    global CLIENT
    global TEXT_LISTENER

    # instantiate and start a global asyncio event loop.
    # pass in the exit_handler coroutine that will be called upon relasing the event loop.
    CLIENT = VirtualClient(disconnect_client)
    TEXT_LISTENER = CodempClientTextChangeListener()

    status_log("plugin loaded")


async def disconnect_client():
    global CLIENT
    global TEXT_LISTENER

    safe_listener_detach(TEXT_LISTENER)
    CLIENT.tm.stop_all()

    for vws in CLIENT.workspaces.values():
        vws.cleanup()

    CLIENT = None


def plugin_unloaded():
    global CLIENT
    # releasing the runtime, runs the disconnect callback defined when acquiring the event loop.
    CLIENT.tm.release(False)
    status_log("plugin unloaded")


# Listeners
##############################################################################
class EventListener(sublime_plugin.EventListener):
    def on_exit(self) -> None:
        global CLIENT
        CLIENT.tm.release(True)


class CodempClientViewEventListener(sublime_plugin.ViewEventListener):
    @classmethod
    def is_applicable(cls, settings):
        return settings.get(g.CODEMP_BUFFER_TAG, False)

    @classmethod
    def applies_to_primary_view_only(cls):
        return False

    def on_selection_modified_async(self):
        s = self.view.settings()

        global CLIENT
        vbuff = CLIENT[s[g.CODEMP_WORKSPACE_ID]].get_by_local(self.view.buffer_id())
        if vbuff is not None:
            CLIENT.send_cursor(vbuff)

    # We only edit on one view at a time, therefore we only need one TextChangeListener
    # Each time we focus a view to write on it, we first attach the listener to that buffer.
    # When we defocus, we detach it.
    def on_activated(self):
        global TEXT_LISTENER

        # sublime has no proper way to check if a view gained or lost input focus outside of this
        # callback (i know right?), so we have to manually keep track of which view has the focus
        g.ACTIVE_CODEMP_VIEW = self.view.id()
        print("view {} activated".format(self.view.id()))
        TEXT_LISTENER.attach(self.view.buffer())

    def on_deactivated(self):
        global TEXT_LISTENER

        g.ACTIVE_CODEMP_VIEW = None
        print("view {} deactivated".format(self.view.id()))
        safe_listener_detach(TEXT_LISTENER)

    def on_pre_close(self):
        global TEXT_LISTENER
        if self.view.id() == g.ACTIVE_CODEMP_VIEW:
            safe_listener_detach(TEXT_LISTENER)

        global CLIENT
        wsid = self.view.settings().get(g.CODEMP_WORKSPACE_ID)
        vbuff = CLIENT[wsid].get_by_local(self.view.buffer_id())
        vbuff.cleanup()

        CLIENT.tm.stop_and_pop(f"{g.BUFFCTL_TASK_PREFIX}-{vbuff.codemp_id}")


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
            status_log("ignoring echoing back the change.")
            s[g.CODEMP_IGNORE_NEXT_TEXT_CHANGE] = False
            return

        global CLIENT
        vbuff = CLIENT[s[g.CODEMP_WORKSPACE_ID]].get_by_local(self.buffer.id())
        CLIENT.send_buffer_change(changes, vbuff)


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
    def run(self, server_host):
        global CLIENT
        rt.dispatch(CLIENT.connect(server_host))

    def input(self, args):
        if "server_host" not in args:
            return ServerHost()

    def input_description(self):
        return "Server host:"


# Generic Join Command
#############################################################################
async def JoinCommand(client: VirtualClient, workspace_id: str, buffer_id: str):
    vws = await client.join_workspace(workspace_id)
    if vws is not None:
        await vws.attach(buffer_id)


class CodempJoinCommand(sublime_plugin.WindowCommand):
    def run(self, workspace_id, buffer_id):
        global CLIENT
        rt.dispatch(JoinCommand(CLIENT, workspace_id, buffer_id))

    def input_description(self):
        return "Join:"

    def input(self, args):
        if "workspace_id" not in args:
            return WorkspaceIdAndFollowup()


# Join Workspace Command
#############################################################################
class CodempJoinWorkspaceCommand(sublime_plugin.WindowCommand):
    def run(self, workspace_id):
        global CLIENT
        rt.dispatch(CLIENT.join_workspace(workspace_id))

    def input_description(self):
        return "Join specific workspace"

    def input(self, args):
        if "workspace_id" not in args:
            return RawWorkspaceId()


# Join Buffer Command
#############################################################################
class CodempJoinBufferCommand(sublime_plugin.WindowCommand):
    def run(self, buffer_id):
        global CLIENT
        if CLIENT.active_workspace is not None:
            sublime.error_message(
                "You haven't joined any worksapce yet. \
                use `Codemp: Join Workspace` or `Codemp: Join`"
            )
            return

        rt.dispatch(CLIENT.active_workspace.attach(buffer_id))

    def input_description(self):
        return "Join buffer in the active workspace"

    # This is awful, fix it
    def input(self, args):
        global CLIENT
        if CLIENT.active_workspace is None:
            sublime.error_message(
                "You haven't joined any worksapce yet. \
                use `Codemp: Join Workspace` or `Codemp: Join`"
            )
            return

        if "buffer_id" not in args:
            existing_buffers = CLIENT.active_workspace.handle.filetree()
            if len(existing_buffers) == 0:
                return RawBufferId()
            else:
                return ListBufferId()


# Text Change Command
#############################################################################
class CodempReplaceTextCommand(sublime_plugin.TextCommand):
    def run(self, edit, start, end, content, change_id):
        # we modify the region to account for any change that happened in the mean time
        region = self.view.transform_region_from(sublime.Region(start, end), change_id)
        self.view.replace(edit, region, content)


# Input Handlers
##############################################################################
class ServerHost(sublime_plugin.TextInputHandler):
    def name(self):
        return "server_host"

    def initial_text(self):
        return "http://127.0.0.1:50051"


class ListBufferId(sublime_plugin.ListInputHandler):
    def name(self):
        return "buffer_id"

    def list_items(self):
        global CLIENT
        return CLIENT.active_workspace.handle.filetree()

    def next_input(self, args):
        if "buffer_id" not in args:
            return RawBufferId()


class RawWorkspaceId(sublime_plugin.TextInputHandler):
    def name(self):
        return "workspace_id"

    def placeholder(self):
        return "Workspace Id"


class WorkspaceIdAndFollowup(sublime_plugin.TextInputHandler):
    def name(self):
        return "workspace_id"

    def placeholder(self):
        return "Workspace Id"

    def next_input(self, args):
        if "buffer_id" not in args:
            return RawBufferId()


class RawBufferId(sublime_plugin.TextInputHandler):
    def name(self):
        return "buffer_id"

    def placeholder(self):
        return "Buffer Id"

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
    def run(self):
        rt.sync(disconnect_client())


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
