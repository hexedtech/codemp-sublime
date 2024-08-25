# pyright: reportIncompatibleMethodOverride=false
import sublime
import sublime_plugin
import logging
import random
from typing import Tuple

import codemp
from Codemp.src.client import client
from Codemp.src.utils import safe_listener_detach
from Codemp.src.utils import safe_listener_attach
from Codemp.src import globals as g

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

TEXT_LISTENER = None

# the actual client gets initialized upon plugin loading as a singleton
# in its own submodule.


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
    # client.disconnect()
    # rt.stop_loop()


# Listeners
##############################################################################
class EventListener(sublime_plugin.EventListener):
    def is_enabled(self):
        return client.codemp is not None

    def on_exit(self):
        client.disconnect()
        client.driver.stop()

    def on_pre_close_window(self, window):
        assert client.codemp is not None
        if not client.valid_window(window):
            return

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
        return settings.get(g.CODEMP_BUFFER_TAG, False)

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
            raise
        vws.send_cursor(vbuff.id, start, end)

    def on_activated(self):
        global TEXT_LISTENER
        safe_listener_attach(TEXT_LISTENER, self.view.buffer())  # pyright: ignore

    def on_deactivated(self):
        global TEXT_LISTENER
        safe_listener_detach(TEXT_LISTENER)  # pyright: ignore

    def on_pre_close(self):
        if self.view == sublime.active_window().active_view():
            global TEXT_LISTENER
            safe_listener_detach(TEXT_LISTENER)  # pyright: ignore

        vws = client.workspace_from_view(self.view)
        vbuff = client.buffer_from_view(self.view)
        if vws is None or vbuff is None:
            raise

        vws.uninstall_buffer(vbuff)

    def on_text_command(self, command_name, args):
        if command_name == "codemp_replace_text":
            logger.info("got a codemp_replace_text command! but in the view listener")

    def on_post_text_command(self, command_name, args):
        if command_name == "codemp_replace_text":
            logger.info("got a codemp_replace_text command! but in the view listener")


class CodempClientTextChangeListener(sublime_plugin.TextChangeListener):
    @classmethod
    def is_applicable(cls, buffer):
        # don't attach this event listener automatically
        # we'll do it by hand with .attach(buffer).
        return False

    # we do the boring stuff in the async thread
    def on_text_changed_async(self, changes):
        s = self.buffer.primary_view().settings()
        if s.get(g.CODEMP_IGNORE_NEXT_TEXT_CHANGE, False):
            logger.debug("Ignoring echoing back the change.")
            s[g.CODEMP_IGNORE_NEXT_TEXT_CHANGE] = False
            return

        vbuff = client.buffer_from_view(self.buffer.primary_view())
        if vbuff is not None:
            # but then we block the main one for the actual sending!
            sublime.set_timeout(lambda: vbuff.send_buffer_change(changes))


# Client Commands:
#   codemp_connect:         connect to a server.
#   codemp_disconnect:      manually call the disconnection, triggering the cleanup and dropping
#                           the connection
#   codemp_join_workspace:  joins a specific workspace, without joining also a buffer
#   codemp_leave_workspace:

# Workspace Commands:
#   codemp_join_buffer:     joins a specific buffer within the current active workspace
#   codemp_leave_buffer:
#   codemp_create_buffer:
#   codemp_delete_buffer:

# Internal commands:
#   replace_text:       swaps the content of a view with the given text.


# Client Commands
#############################################################################
# Connect Command
class CodempConnectCommand(sublime_plugin.WindowCommand):
    def is_enabled(self) -> bool:
        return client.codemp is None

    def run(self, server_host, user_name, password="lmaodefaultpassword"):
        logger.info(f"Connecting to {server_host} with user {user_name}...")

        def try_connect():
            try:
                client.connect(server_host, user_name, password)
            except Exception as e:
                logger.error(f"Could not connect: {e}")
                sublime.error_message(
                    "Could not connect:\n Make sure the server is up\n\
                    and your credentials are correct."
                )

        sublime.set_timeout_async(try_connect)

    def input_description(self):
        return "Server host:"

    def input(self, args):
        if "server_host" not in args:
            return SimpleTextInput(
                ("server_host", "http://127.0.0.1:50051"),
                ("user_name", f"user-{random.random()}"),
            )


# Disconnect Command
class CodempDisconnectCommand(sublime_plugin.WindowCommand):
    def is_enabled(self):
        return client.codemp is not None

    def run(self):
        client.disconnect()


# Join Workspace Command
class CodempJoinWorkspaceCommand(sublime_plugin.WindowCommand):
    def is_enabled(self) -> bool:
        return client.codemp is not None

    def run(self, workspace_id):
        assert client.codemp is not None
        if client.valid_workspace(workspace_id):
            logger.info(f"Joining workspace: '{workspace_id}'...")
            promise = client.codemp.join_workspace(workspace_id)
            active_window = sublime.active_window()

            def defer_instantiation(promise):
                try:
                    workspace = promise.wait()
                except Exception as e:
                    logger.error(
                        f"Could not join workspace '{workspace_id}'.\n\nerror: {e}"
                    )
                    sublime.error_message(f"Could not join workspace '{workspace_id}'")
                    return
                client.install_workspace(workspace, active_window)

            sublime.set_timeout_async(lambda: defer_instantiation(promise))
        # the else shouldn't really happen, and if it does, it should already be instantiated.
        # ignore.

    def input_description(self):
        return "Join:"

    def input(self, args):
        if "workspace_id" not in args:
            return SimpleTextInput(("workspace_id", ""))


# To allow for having a selection and choosing non existing workspaces
# we do a little dance: We pass this list input handler to a TextInputHandler
# when we select "Create New..." which adds his result to the list of possible
# workspaces and pop itself off the stack to go back to the list handler.
# class WorkspaceIdList(sublime_plugin.ListInputHandler):
#     def __init__(self):
#         assert client.codemp is not None  # the command should not be available

#         # at the moment, the client can't give us a full list of existing workspaces
#         # so a textinputhandler would be more appropriate. but we keep this for the future

#         self.add_entry_text = "* add entry..."
#         self.list = client.codemp.active_workspaces()
#         self.list.sort()
#         self.list.append(self.add_entry_text)
#         self.preselected = None

#     def name(self):
#         return "workspace_id"

#     def placeholder(self):
#         return "Workspace"

#     def list_items(self):
#         if self.preselected is not None:
#             return (self.list, self.preselected)
#         else:
#             return self.list

#     def next_input(self, args):
#         if args["workspace_id"] == self.add_entry_text:
#             return AddListEntry(self)


# Leave Workspace Command
class CodempLeaveWorkspaceCommand(sublime_plugin.WindowCommand):
    def is_enabled(self):
        return client.codemp is not None and len(client.all_workspaces(self.window)) > 0

    def run(self, workspace_id: str):
        # client.leave_workspace(id)
        pass

    def input(self, args):
        if "id" not in args:
            return ActiveWorkspacesIdList()


# WORKSPACE COMMANDS
#############################################################################


# Join Buffer Command
class CodempJoinBufferCommand(sublime_plugin.WindowCommand):
    def is_enabled(self):
        available_workspaces = client.all_workspaces(self.window)
        return len(available_workspaces) > 0

    def run(self, workspace_id, buffer_id):
        # A workspace has some Buffers inside of it (filetree)
        # some of those you are already attached to
        # If already attached to it return the same alredy existing bufferctl
        # if existing but not attached (attach)
        # if not existing ask for creation (create + attach)
        vws = client.workspace_from_id(workspace_id)
        assert vws is not None
        # is the buffer already installed?
        if vws.valid_buffer(buffer_id):
            return  # do nothing.

        if buffer_id not in vws.codemp.filetree(filter=buffer_id):
            create = sublime.ok_cancel_dialog(
                "There is no buffer named '{buffer_id}' in the workspace '{workspace_id}'.\n\
                Do you want to create it?",
                ok_title="yes",
                title="Create Buffer?",
            )
            if create:
                try:
                    create_promise = vws.codemp.create(buffer_id)
                except Exception as e:
                    logging.error(f"could not create buffer:\n\n {e}")
                    return
                create_promise.wait()

        # now we can defer the attaching process
        promise = vws.codemp.attach(buffer_id)

        def deferred_attach(promise):
            try:
                buff_ctl = promise.wait()
            except Exception as e:
                logging.error(f"error when attaching to buffer '{id}':\n\n {e}")
                sublime.error_message(f"Could not attach to buffer '{buffer_id}'")
                return
            vbuff = vws.install_buffer(buff_ctl)
            # TODO! if the view is already active calling focus_view() will not trigger the on_activate
            self.window.focus_view(vbuff.view)

        sublime.set_timeout_async(lambda: deferred_attach(promise))

    def input_description(self) -> str:
        return "Attach: "

    def input(self, args):
        if "workspace_id" not in args:
            return ActiveWorkspacesIdList(self.window, get_buffer=True)

        if "buffer_id" not in args:
            return BufferIdList(args["workspace_id"])


# Leave Buffer Comand
class CodempLeaveBufferCommand(sublime_plugin.WindowCommand):
    def is_enabled(self):
        return len(client.all_buffers()) > 0

    def run(self, workspace_id, buffer_id):
        vbuff = client.buffer_from_id(buffer_id)
        vws = client.workspace_from_id(workspace_id)

        if vbuff is None or vws is None:
            sublime.error_message(f"You are not attached to the buffer '{id}'")
            logging.warning(f"You are not attached to the buffer '{id}'")
            return

        def defer_detach():
            if vws.codemp.detach(buffer_id):
                vws.uninstall_buffer(vbuff)

        sublime.set_timeout_async(defer_detach)

    def input_description(self) -> str:
        return "Leave: "

    def input(self, args):
        if "workspace_id" not in args:
            return ActiveWorkspacesIdList(self.window, get_buffer=True)

        if "buffer_id" not in args:
            return BufferIdList(args["workspace_id"])


# Leave Buffer Comand
class CodempCreateBufferCommand(sublime_plugin.WindowCommand):
    def is_enabled(self):
        return len(client.all_workspaces(self.window)) > 0

    def run(self, workspace_id, buffer_id):
        vws = client.workspace_from_id(workspace_id)

        if vws is None:
            sublime.error_message(
                f"You are not attached to the workspace '{workspace_id}'"
            )
            logging.warning(f"You are not attached to the workspace '{workspace_id}'")
            return

        vws.codemp.create(buffer_id)
        logging.info(
            "created buffer '{buffer_id}' in the workspace '{workspace_id}'.\n\
            To interact with it you need to attach to it with Codemp: Attach."
        )

    def input_description(self) -> str:
        return "Create Buffer: "

    def input(self, args):
        if "workspace_id" not in args:
            return ActiveWorkspacesIdList(self.window, get_buffer=True)

        if "buffer_id" not in args:
            return SimpleTextInput(("buffer_id", "new buffer"))


class CodempDeleteBufferCommand(sublime_plugin.WindowCommand):
    def is_enabled(self):
        return len(client.all_buffers()) > 0

    def run(self, workspace_id, buffer_id):
        vws = client.workspace_from_id(workspace_id)
        if vws is None:
            sublime.error_message(
                f"You are not attached to the workspace '{workspace_id}'"
            )
            logging.warning(f"You are not attached to the workspace '{workspace_id}'")
            return

        fetch_promise = vws.codemp.fetch_buffers()
        delete = sublime.ok_cancel_dialog(
            f"Confirm you want to delete the buffer '{buffer_id}'",
            ok_title="delete",
            title="Delete Buffer?",
        )
        if not delete:
            return
        fetch_promise.wait()
        existing = vws.codemp.filetree(buffer_id)
        if len(existing) == 0:
            sublime.error_message(
                f"The buffer '{buffer_id}' does not exists in the workspace."
            )
            logging.info(f"The buffer '{buffer_id}' does not exists in the workspace.")
            return

        def deferred_delete():
            try:
                vws.codemp.delete(buffer_id).wait()
            except Exception as e:
                logging.error(f"error when deleting the buffer '{id}':\n\n {e}", True)
                return

        vbuff = client.buffer_from_id(buffer_id)
        if vbuff is None:
            # we are not attached to it!
            sublime.set_timeout_async(deferred_delete)
        else:
            if vws.codemp.detach(buffer_id):
                vws.uninstall_buffer(vbuff)
                sublime.set_timeout_async(deferred_delete)
            else:
                logging.error(
                    f"error while detaching from buffer '{buffer_id}', aborting the delete."
                )
                return

    def input_description(self) -> str:
        return "Delete buffer: "

    def input(self, args):
        if "workspace_id" not in args:
            return ActiveWorkspacesIdList(self.window, get_buffer=True)

        if "buffer_id" not in args:
            return BufferIdList(args["workspace_id"])


# Text Change Command
#############################################################################
class CodempReplaceTextCommand(sublime_plugin.TextCommand):
    def run(self, edit, start, end, content, change_id):
        # we modify the region to account for any change that happened in the mean time
        region = self.view.transform_region_from(sublime.Region(start, end), change_id)
        self.view.replace(edit, region, content)


# Input handlers
############################################################
class SimpleTextInput(sublime_plugin.TextInputHandler):
    def __init__(self, *args: Tuple[str, str]):
        assert len(args) > 0
        self.argname = args[0][0]
        self.default = args[0][1]
        self.next_inputs = args[1:]

    def initial_text(self):
        return self.default

    def name(self):
        return self.argname

    def next_input(self, args):
        if len(self.next_inputs) > 0:
            if self.next_inputs[0][0] not in args:
                return SimpleTextInput(*self.next_inputs)


class ActiveWorkspacesIdList(sublime_plugin.ListInputHandler):
    def __init__(self, window=None, get_buffer=False):
        self.window = window
        self.get_buffer = get_buffer

    def name(self):
        return "workspace_id"

    def list_items(self):
        return [vws.id for vws in client.all_workspaces(self.window)]

    def next_input(self, args):
        if self.get_buffer:
            return BufferIdList(args["workspace_id"])


class BufferIdList(sublime_plugin.ListInputHandler):
    def __init__(self, workspace_id):
        self.add_entry_text = "* create new..."
        self.list = [vbuff.id for vbuff in client.all_buffers(workspace_id)]
        self.list.sort()
        self.list.append(self.add_entry_text)
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

    def next_input(self, args):
        if args["buffer_id"] == self.add_entry_text:
            return AddListEntry(self)


class AddListEntry(sublime_plugin.TextInputHandler):
    # this class works when the list input handler
    # added appended a new element to it's list that will need to be
    # replaced with the entry added from here!
    def __init__(self, list_input_handler):
        self.parent = list_input_handler

    def name(self):
        return None

    def validate(self, text: str) -> bool:
        return not len(text) == 0

    def confirm(self, text: str):
        self.parent.list.pop()  # removes the add_entry_text
        self.parent.list.insert(0, text)
        self.parent.preselected = 0

    def next_input(self, args):
        return sublime_plugin.BackInputHandler()


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
