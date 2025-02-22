import sublime
import sublime_plugin
import logging
import os

from ..core.session import session
from ..core.workspace import workspaces
from ..core.buffers import buffers

from ..text_listener import TEXT_LISTENER
from ..utils import some
from ..input_handlers import SimpleListInput, SimpleTextInput

logger = logging.getLogger(__name__)

# Join Buffer Command
class CodempJoinBufferCommand(sublime_plugin.WindowCommand):
    def is_enabled(self):
        return len(workspaces.lookup(self.window)) > 0

    def input_description(self) -> str:
        return "Join Buffer: "

    def input(self, args):
        for name in ["workspace_id", "buffer_id"]:
            if name not in args:
                if name == "workspace_id":
                    wslist = session.client.active_workspaces()
                    return SimpleListInput(
                        ("workspace_id", wslist),
                    )

                if name == "buffer_id":
                    try: ws = workspaces.lookupId(args["workspace_id"])
                    except KeyError:
                        sublime.error_message("Workspace does not exists or is not active.")
                        return None

                    bflist = ws.handle.fetch_buffers().wait()
                    if bflist:
                        return SimpleListInput(
                            ("buffer_id", bflist)
                        )
                    else:
                        sublime.error_message("Workspace does not have any buffers inside.")
                        return None

    def run(self, workspace_id, buffer_id): # pyright: ignore[reportIncompatibleMethodOverride]
        if not buffer_id:
            return

        try: vws = workspaces.lookupId(workspace_id)
        except KeyError:
            logger.error(f"Can't create buffer: '{workspace_id}' does not exists or is not active.")
            return

        try: # if it exists already, focus and listen
            buff = buffers.lookupId(buffer_id)
            self.window.focus_view(buff.view)
            return
        except KeyError:
            pass

        logger.debug(f"attempting to attach to {buffer_id}...")

        def _():
            vbuff = some(buffers.register(buffer_id, vws))
            vbuff.sync(TEXT_LISTENER)

        sublime.set_timeout_async(_)

# Leave Buffer Comand
class CodempLeaveBufferCommand(sublime_plugin.WindowCommand):
    def is_enabled(self):
        return len(buffers.lookup()) > 0

    def input_description(self) -> str:
        return "Leave: "

    def input(self, args):
        if "buffer_id" not in args:
            return SimpleListInput(
                ("buffer_id", [bf.id for bf in buffers.lookup()])
            )

    def run(self, buffer_id): # pyright: ignore[reportIncompatibleMethodOverride]
        if buffer_id not in buffers:
            logger.warning(f"The buffer was already removed:  '{buffer_id}'")
            return

        # The call must happen separately, otherwise it causes sublime to crash...
        # no idea why...
        sublime.set_timeout(lambda: buffers.remove(buffer_id), 10)
        def _():
            buffers.remove(buffer_id)
            if not vws.handle.detach_buffer(buffer_id):
                logger.error(f"could not leave the buffer {buffer_id}.")
            else:
                logger.debug(f"successfully detached from {buffer_id}.")
        sublime.set_timeout(_, 10)

# Leave Buffer Comand
class CodempCreateBufferCommand(sublime_plugin.WindowCommand):
    def is_enabled(self):
        return workspaces.hasactive()

    def run(self, workspace_id, buffer_id):# pyright: ignore[reportIncompatibleMethodOverride]
        try: vws = workspaces.lookupId(workspace_id)
        except KeyError:
            sublime.error_message(f"You are not attached to the workspace '{workspace_id}'")
            logger.warning(f"You are not attached to the workspace '{workspace_id}'")
            return

        vws.handle.create_buffer(buffer_id).wait()
        logger.info(
            f"created buffer '{buffer_id}' in the workspace '{workspace_id}'.\n\
            To interact with it you need to attach to it with Codemp: Attach."
        )

class CodempDeleteBufferCommand(sublime_plugin.WindowCommand):
    def is_enabled(self):
        return len(workspaces.lookup()) > 0

    def run(self, workspace_id, buffer_id):# pyright: ignore[reportIncompatibleMethodOverride]

        try: vws = workspaces.lookupId(workspace_id)
        except KeyError:
            sublime.error_message(f"You are not attached to the workspace {workspace_id}")
            logger.warning(f"You are not attached to the workspace {workspace_id}")
            return

        if buffer_id in buffers:

            if not sublime.ok_cancel_dialog(
                f"You are currently attached to '{buffer_id}'.\n\
                Do you want to detach and delete it?",
                ok_title="yes", title="Delete Buffer?",
            ): return

            self.window.run_command(
                "codemp_leave_buffer", {"buffer_id": buffer_id })

        else:
            if not sublime.ok_cancel_dialog(
                f"Confirm you want to delete the buffer '{buffer_id}'",
                ok_title="delete", title="Delete Buffer?",
            ): return

        vws.handle.delete_buffer(buffer_id).wait()

