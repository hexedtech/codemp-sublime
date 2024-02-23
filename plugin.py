import sublime
import sublime_plugin

from Codemp.src.codemp_client import VirtualClient
from Codemp.src.TaskManager import rt
from Codemp.src.utils import status_log, is_active, safe_listener_detach
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

    # fix me: allow riconnections
    CLIENT = None


def plugin_unloaded():
    global CLIENT
    # releasing the runtime, runs the disconnect callback defined when acquiring the event loop.
    CLIENT.tm.release(False)
    status_log("plugin unloaded")


# Utils
##############################################################################


def get_contents(view):
    r = sublime.Region(0, view.size())
    return view.substr(r)


def populate_view(view, content):
    view.run_command(
        "codemp_replace_text",
        {
            "start": 0,
            "end": view.size(),
            "content": content,
            "change_id": view.change_id(),
        },
    )


def get_view_from_local_path(path):
    for window in sublime.windows():
        for view in window.views():
            if view.file_name() == path:
                return view


# Listeners
##############################################################################
class EventListener(sublime_plugin.EventListener):
    def on_exit(self) -> None:
        global CLIENT
        CLIENT.tm.release(True)


class CodempClientViewEventListener(sublime_plugin.ViewEventListener):
    @classmethod
    def is_applicable(cls, settings):
        return settings.get(g.CODEMP_BUFFER_VIEW_TAG, False)

    @classmethod
    def applies_to_primary_view_only(cls):
        return False

    def on_selection_modified_async(self):
        global CLIENT
        vbuff = CLIENT.active_workspace.get_by_local(self.view.buffer_id())
        if vbuff is not None:
            CLIENT.send_cursor(vbuff)

    # We only edit on one view at a time, therefore we only need one TextChangeListener
    # Each time we focus a view to write on it, we first attach the listener to that buffer.
    # When we defocus, we detach it.
    def on_activated(self):
        global TEXT_LISTENER
        print("view {} activated".format(self.view.id()))
        TEXT_LISTENER.attach(self.view.buffer())

    def on_deactivated(self):
        global TEXT_LISTENER
        print("view {} deactivated".format(self.view.id()))
        safe_listener_detach(TEXT_LISTENER)

    def on_pre_close(self):
        global TEXT_LISTENER
        if is_active(self.view):
            safe_listener_detach(TEXT_LISTENER)

        global CLIENT
        vbuff = CLIENT.active_workspace.get_by_local(self.view.buffer_id())
        vbuff.cleanup()

        CLIENT.tm.stop_and_pop(f"{g.BUFFCTL_TASK_PREFIX}-{vbuff.codemp_id}")
        # have to run the detach logic in sync, to keep a valid reference to the view.
        # sublime_asyncio.sync(buffer.detach(_client))


class CodempClientTextChangeListener(sublime_plugin.TextChangeListener):
    @classmethod
    def is_applicable(cls, buffer):
        # don't attach this event listener automatically
        # we'll do it by hand with .attach(buffer).
        return False

    # blocking :D
    def on_text_changed(self, changes):
        if (
            self.buffer.primary_view()
            .settings()
            .get(g.CODEMP_IGNORE_NEXT_TEXT_CHANGE, None)
        ):
            status_log("ignoring echoing back the change.")
            self.view.settings()[g.CODEMP_IGNORE_NEXT_TEXT_CHANGE] = False
            return

        global CLIENT
        vbuff = CLIENT.active_workspace.get_by_local(self.buffer.id())
        CLIENT.send_buffer_change(changes, vbuff)


# Commands:
#   codemp_connect:     connect to a server.
#   codemp_join:        join a workspace with a given name within the server.
#   codemp_share:       shares a buffer with a given name in the workspace.
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
            return ServerHostInputHandler()

    def input_description(self):
        return "Server host:"


class ServerHostInputHandler(sublime_plugin.TextInputHandler):
    def initial_text(self):
        return "http://127.0.0.1:50051"


# Join Workspace Command
#############################################################################
class CodempJoinCommand(sublime_plugin.WindowCommand):
    def run(self, workspace_id):
        global CLIENT
        rt.dispatch(CLIENT.join_workspace(workspace_id))

    def input_description(self):
        return "Join Workspace:"

    def input(self, args):
        if "workspace_id" not in args:
            return WorkspaceIdInputHandler()


class WorkspaceIdInputHandler(sublime_plugin.TextInputHandler):
    def initial_text(self):
        return "What workspace should I join?"


# Join Buffer Command
#############################################################################
class CodempAttachCommand(sublime_plugin.WindowCommand):
    def run(self, buffer_id):
        global CLIENT
        if CLIENT.active_workspace is not None:
            rt.dispatch(CLIENT.active_workspace.attach(buffer_id))
        else:
            sublime.error_message(
                "You haven't joined any worksapce yet. use `Codemp: Join Workspace`"
            )

    def input_description(self):
        return "Join Buffer in workspace:"

    # This is awful, fix it
    def input(self, args):
        global CLIENT
        if CLIENT.active_workspace is not None:
            if "buffer_id" not in args:
                existing_buffers = CLIENT.active_workspace.handle.filetree()
                if len(existing_buffers) == 0:
                    return BufferIdInputHandler()
                else:
                    return ListBufferIdInputHandler()
        else:
            sublime.error_message(
                "You haven't joined any worksapce yet. use `Codemp: Join Workspace`"
            )
            return


class BufferIdInputHandler(sublime_plugin.TextInputHandler):
    def initial_text(self):
        return "No buffers found in the workspace. Create new: "


class ListBufferIdInputHandler(sublime_plugin.ListInputHandler):
    def name(self):
        return "buffer_id"

    def list_items(self):
        global CLIENT
        return CLIENT.active_workspace.handle.filetree()

    def next_input(self, args):
        if "buffer_id" not in args:
            return BufferIdInputHandler()


# Text Change Command
#############################################################################
# we call this command manually to have access to the edit token.
class CodempReplaceTextCommand(sublime_plugin.TextCommand):
    def run(self, edit, start, end, content, change_id):
        # we modify the region to account for any change that happened in the mean time
        print("running the replace command, launche manually.")
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


# class SublimeBufferPathInputHandler(sublime_plugin.ListInputHandler):
#     def list_items(self):
#         ret_list = []

#         for window in sublime.windows():
#             for view in window.views():
#                 if view.file_name():
#                     ret_list.append(view.file_name())

#         return ret_list

#     def next_input(self, args):
#         if "server_id" not in args:
#             return ServerIdInputHandler()


# class ServerIdInputHandler(sublime_plugin.TextInputHandler):
#     def initial_text(self):
#         return "Buffer name on server"


# Disconnect Command
#############################################################################
class CodempDisconnectCommand(sublime_plugin.WindowCommand):
    def run(self):
        rt.sync(disconnect_client())


# Proxy Commands ( NOT USED )
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
#
# class ProxyCodempJoinCommand(sublime_plugin.WindowCommand):
#   def run(self, **kwargs):
#       self.window.run_command("codemp_join", kwargs)
#
#   def input(self, args):
#       if 'server_buffer' not in args:
#           return ServerBufferInputHandler()
#
#   def input_description(self):
#       return 'Join Buffer:'
#
# class ProxyCodempConnectCommand(sublime_plugin.WindowCommand):
#   # on_window_command, does not trigger when called from the command palette
#   # See: https://github.com/sublimehq/sublime_text/issues/2234
#   def run(self, **kwargs):
#       self.window.run_command("codemp_connect", kwargs)
#
#   def input(self, args):
#       if 'server_host' not in args:
#           return ServerHostInputHandler()
#
#   def input_description(self):
#       return 'Server host:'


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
