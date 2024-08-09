# pyright: reportIncompatibleMethodOverride=false

import sublime
import sublime_plugin
import random

# import os
# import sys
# import importlib.util

from .src.TaskManager import tm
from .src.client import client, VirtualClient
from .src.client import CodempLogger
from .src.utils import status_log
from .src.utils import safe_listener_detach
from .src.utils import safe_listener_attach
from .src import globals as g


TEXT_LISTENER = None

# Initialisation and Deinitialisation
##############################################################################


def plugin_loaded():
    global TEXT_LISTENER

    # instantiate and start a global asyncio event loop.
    # pass in the exit_handler coroutine that will be called upon relasing the event loop.
    tm.acquire(disconnect_client)

    logger = CodempLogger()

    tm.dispatch(logger.log(), "codemp-logger")

    TEXT_LISTENER = CodempClientTextChangeListener()

    status_log("plugin loaded")


async def disconnect_client():
    global TEXT_LISTENER

    tm.stop_all()

    if TEXT_LISTENER is not None:
        safe_listener_detach(TEXT_LISTENER)

    for vws in client.workspaces.values():
        vws.cleanup()


def plugin_unloaded():
    # releasing the runtime, runs the disconnect callback defined when acquiring the event loop.
    status_log("unloading")
    tm.release(False)


# Listeners
##############################################################################
class EventListener(sublime_plugin.EventListener):
    def on_exit(self):
        tm.release(True)

    def on_pre_close_window(self, window):
        if client.active_workspace is None:
            return  # nothing to do

        client.make_active(None)

        s = window.settings()
        if not s.get(g.CODEMP_WINDOW_TAG, False):
            return

        for wsid in s[g.CODEMP_WINDOW_WORKSPACES]:
            ws = client[wsid]
            if ws is None:
                status_log(
                    "[WARN] a tag on the window was found but not a matching workspace."
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
            status_log("Ignoring echoing back the change.")
            s[g.CODEMP_IGNORE_NEXT_TEXT_CHANGE] = False
            return

        vbuff = client.get_buffer(self.buffer.primary_view())
        if vbuff is not None:
            vbuff.send_buffer_change(changes)


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
            return ConnectUserName()


class ConnectUserName(sublime_plugin.TextInputHandler):
    def name(self):
        return "user_name"

    def initial_text(self):
        return f"user-{random.random()}"


# Generic Join Command
#############################################################################
async def JoinCommand(client: VirtualClient, workspace_id: str, buffer_id: str):
    if workspace_id is None:
        return

    vws = await client.join_workspace(workspace_id)

    if buffer_id is None:
        return

    if vws is not None:
        await vws.attach(buffer_id)


class CodempJoinCommand(sublime_plugin.WindowCommand):
    def run(self, workspace_id, buffer_id):
        tm.dispatch(JoinCommand(client, workspace_id, buffer_id))

    def input_description(self):
        return "Join:"

    def input(self, args):
        if "workspace_id" not in args:
            return WorkspaceIdAndFollowup()


class WorkspaceIdAndFollowup(sublime_plugin.ListInputHandler):
    def name(self):
        return "workspace_id"

    def placeholder(self):
        return "Workspace Id"

    def list_items(self):
        return client.active_workspaces()

    def next_input(self, args):
        if "buffer_id" not in args:
            return ListBufferId()


class ListBufferId(sublime_plugin.ListInputHandler):
    def name(self):
        return "buffer_id"

    def placeholder(self):
        return "Buffer Id"

    def list_items(self):
        return client.active_workspace.handle.filetree()


# Join Workspace Command
#############################################################################
class CodempJoinWorkspaceCommand(sublime_plugin.WindowCommand):
    def run(self, workspace_id):  # pyright: ignore
        tm.dispatch(client.join_workspace(workspace_id))

    def input_description(self):
        return "Join specific workspace"

    def input(self, args):
        if "workspace_id" not in args:
            return RawWorkspaceId()


# Join Buffer Command
#############################################################################
class CodempJoinBufferCommand(sublime_plugin.WindowCommand):
    def run(self, buffer_id):  # pyright: ignore
        if client.active_workspace is None:
            sublime.error_message(
                "You haven't joined any worksapce yet. \
                use `Codemp: Join Workspace` or `Codemp: Join`"
            )
            return

        tm.dispatch(client.active_workspace.attach(buffer_id))

    def input_description(self):
        return "Join buffer in the active workspace"

    # This is awful, fix it
    def input(self, args):
        if client.active_workspace is None:
            sublime.error_message(
                "You haven't joined any worksapce yet. \
                use `Codemp: Join Workspace` or `Codemp: Join`"
            )
            return

        if "buffer_id" not in args:
            existing_buffers = client.active_workspace.handle.filetree()
            if len(existing_buffers) == 0:
                return RawBufferId()
            else:
                return ListBufferId2()


# Text Change Command
#############################################################################
class CodempReplaceTextCommand(sublime_plugin.TextCommand):
    def run(self, edit, start, end, content, change_id):
        # we modify the region to account for any change that happened in the mean time
        region = self.view.transform_region_from(sublime.Region(start, end), change_id)
        self.view.replace(edit, region, content)


# Input Handlers
##############################################################################


class ListBufferId2(sublime_plugin.ListInputHandler):
    def name(self):
        return "buffer_id"

    def list_items(self):
        assert client.active_workspace is not None
        return client.active_workspace

    def next_input(self, args):
        if "buffer_id" not in args:
            return RawBufferId()


class RawWorkspaceId(sublime_plugin.TextInputHandler):
    def name(self):
        return "workspace_id"

    def placeholder(self):
        return "Workspace Id"


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
        tm.sync(disconnect_client())


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
