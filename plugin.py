import sublime
import sublime_plugin

# import Codemp.codemp_client as codemp
from Codemp.src.codemp_client import (
    VirtualClient,
    status_log,
    safe_listener_detach,
    is_active,
)xs

# UGLYYYY, find a way to not have global variables laying around.
_client = None
_txt_change_listener = None

_palette = [
    "var(--redish)",
    "var(--orangish)",
    "var(--yellowish)",
    "var(--greenish)",
    "var(--cyanish)",
    "var(--bluish)",
    "var(--purplish)",
    "var(--pinkish)",
]

_regions_colors = [
    "region.redish",
    "region.orangeish",
    "region.yellowish",
    "region.greenish",
    "region.cyanish",
    "region.bluish",
    "region.purplish",
    "region.pinkish",
]


# Initialisation and Deinitialisation
##############################################################################


def plugin_loaded():
    global _client
    global _txt_change_listener

    # instantiate and start a global asyncio event loop.
    # pass in the exit_handler coroutine that will be called upon relasing the event loop.
    _client = VirtualClient(disconnect_client)
    _txt_change_listener = CodempClientTextChangeListener()

    status_log("plugin loaded")


async def disconnect_client():
    global _client
    global _txt_change_listener

    safe_listener_detach(_txt_change_listener)
    _client.tm.stop_all()

    for vws in _client.workspaces:
        vws.cleanup()

    # fime: allow riconnections
    _client = None


def plugin_unloaded():
    global _client
    # releasing the runtime, runs the disconnect callback defined when acquiring the event loop.
    _client.tm.release(False)
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


def cleanup_tags(view):
    del view.settings()["codemp_buffer"]
    view.erase_status("z_codemp_buffer")
    view.erase_regions("codemp_cursors")


def tag(view):
    view.set_status("z_codemp_buffer", "[Codemp]")
    view.settings()["codemp_buffer"] = True

# The main workflow:
# Plugin loads and initialises an empty handle to the client
# The plugin calls connect and populates the handle with a client instance
# We use the client to authenticate and login (to a workspace) to obtain a token
# We join a workspace (either new or existing)


# Listeners
##############################################################################


class CodempClientViewEventListener(sublime_plugin.ViewEventListener):
    @classmethod
    def is_applicable(cls, settings):
        return settings.get("codemp_buffer", False)

    @classmethod
    def applies_to_primary_view_only(cls):
        return False

    def on_selection_modified_async(self):
        global _client
        vbuff = _client.active_workspace.get_virtual_by_local(self.view.buffer_id())
        if vbuff is not None:
            _client.send_cursor(vbuff)

    # We only edit on one view at a time, therefore we only need one TextChangeListener
    # Each time we focus a view to write on it, we first attach the listener to that buffer.
    # When we defocus, we detach it.
    def on_activated(self):
        global _txt_change_listener
        print("view {} activated".format(self.view.id()))
        _txt_change_listener.attach(self.view.buffer())

    def on_deactivated(self):
        global _txt_change_listener
        print("view {} deactivated".format(self.view.id()))
        safe_listener_detach(_txt_change_listener)

    def on_text_command(self, command_name, args):
        print(self.view.id(), command_name, args)
        if command_name == "codemp_replace_text":
            print("dry_run: detach text listener")

    def on_post_text_command(self, command_name, args):
        print(command_name, args)
        if command_name == "codemp_replace_text":
            print("dry_run: attach text listener")

    # UPDATE ME

    def on_pre_close(self):
        global _client
        global _txt_change_listener
        if is_active(self.view):
            safe_listener_detach(_txt_change_listener)

        vbuff = _client.active_workspace.get_virtual_by_local(self.view.buffer_id())
        vbuff.cleanup()

        print(list(map(lambda x: x.get_name(), _client.tm.tasks)))
        task = _client.tm.cancel_and_pop(f"buffer-ctl-{vbuff.codemp_id}")
        print(list(map(lambda x: x.get_name(), _client.tm.tasks)))
        print(task.cancelled())
        # have to run the detach logic in sync, to keep a valid reference to the view.
        # sublime_asyncio.sync(buffer.detach(_client))


class CodempClientTextChangeListener(sublime_plugin.TextChangeListener):
    @classmethod
    def is_applicable(cls, buffer):
        # don't attach this event listener automatically
        # we'll do it by hand with .attach(buffer).
        return False

    # lets make this blocking :D
    # def on_text_changed_async(self, changes):
    def on_text_changed(self, changes):
        global _client
        if (
            self.buffer.primary_view()
            .settings()
            .get("codemp_ignore_next_on_modified_text_event", None)
        ):
            status_log("ignoring echoing back the change.")
            self.view.settings()["codemp_ignore_next_on_modified_text_event"] = False
            return
        vbuff = _client.active_workspace.get_virtual_by_local(self.buffer.id())
        _client.send_buffer_change(changes, vbuff)


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
        global _client
        sublime_asyncio.dispatch(_client.connect(server_host))

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
        global _client
        sublime_asyncio.dispatch(_client.join_workspace(workspace_id))

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
        global _client
        if _client.active_workspace is not None:
            sublime_asyncio.dispatch(_client.active_workspace.attach(buffer_id))
        else:
            sublime.error_message(
                "You haven't joined any worksapce yet. use `Codemp: Join Workspace`"
            )

    def input_description(self):
        return "Join Buffer in workspace:"

    # This is awful, fix it
    def input(self, args):
        global _client
        if _client.active_workspace is not None:
            if "buffer_id" not in args:
                existing_buffers = _client.active_workspace.handle.filetree()
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
        return "Create New Buffer:"


class ListBufferIdInputHandler(sublime_plugin.ListInputHandler):
    def name(self):
        return "buffer_id"

    def list_items(self):
        global _client
        return _client.active_workspace.handle.filetree()

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
        sublime_asyncio.sync(disconnect_client())


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
