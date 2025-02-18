import sublime
import sublime_plugin
import logging
import gc

from ..core.session import session
from ..core.workspace import workspaces
from ..core.buffers import buffers

from ..text_listener import TEXT_LISTENER
from ..utils import safe_listener_attach, safe_listener_detach, populate_view
from ..input_handlers import SimpleListInput, SimpleTextInput

logger = logging.getLogger(__name__)

# Join Buffer Command
class CodempJoinBufferCommand(sublime_plugin.WindowCommand):
    def is_enabled(self):
        return len(workspaces.lookup(self.window)) > 0

    def input_description(self) -> str:
        return "Join Buffer: "

    def input(self, args):
        if "workspace_id" not in args:
            wslist = session.client.active_workspaces()
            return SimpleListInput(
                ("workspace_id", wslist),
            )

        if "buffer_id" not in args:
            try: ws = workspaces.lookupId(args["workspace_id"])
            except KeyError:
                sublime.error_message("Workspace does not exists or is not active.")
                return None

            bflist = ws.handle.fetch_buffers().wait()
            return SimpleListInput(
                ("buffer_id", bflist),
            )

    def run(self, workspace_id, buffer_id): # pyright: ignore[reportIncompatibleMethodOverride]
        try: vws = workspaces.lookupId(workspace_id)
        except KeyError:
            logger.error(f"Can't create buffer: '{workspace_id}' does not exists or is not active.")
            return

        try: # if it exists already, focus and listen
            buff = buffers.lookupId(buffer_id)
            # safe_listener_detach(TEXT_LISTENER)
            # safe_listener_attach(TEXT_LISTENER, buff.view.buffer())
            self.window.focus_view(buff.view)
            return
        except KeyError:
            pass

        # now we can defer the attaching process
        logger.debug(f"attempting to attach to {buffer_id}...")
        ctl_promise = vws.handle.attach_buffer(buffer_id)

        def _():
            try:
                buff_ctl = ctl_promise.wait()
                logger.debug("attach successfull!")
            except Exception as e:
                logging.error(f"error when attaching to buffer '{id}':\n\n {e}")
                sublime.error_message(f"Could not attach to buffer '{buffer_id}'")
                return


            vbuff = buffers.register(buff_ctl, vws)
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
        try:
            buff = buffers.lookupId(buffer_id)
            vws = buffers.lookupParent(buff)
        except KeyError:
            sublime.error_message(f"You are not attached to the buffer '{buffer_id}'")
            logging.warning(f"You are not attached to the buffer '{buffer_id}'")
            return

        if not vws.handle.get_buffer(buffer_id):
            logging.error("The desired buffer is not managed by the workspace.")
            return

        # The call must happen separately, otherwise it causes sublime to crash...
        # no idea why...
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
        return len(workspaces.lookup()) > 0

    def run(self, workspace_id, buffer_id):# pyright: ignore[reportIncompatibleMethodOverride]
        try: vws = workspaces.lookupId(workspace_id)
        except KeyError:
            sublime.error_message(f"You are not attached to the workspace '{workspace_id}'")
            logging.warning(f"You are not attached to the workspace '{workspace_id}'")
            return

        vws.handle.create_buffer(buffer_id)
        logging.info(
            "created buffer '{buffer_id}' in the workspace '{workspace_id}'.\n\
            To interact with it you need to attach to it with Codemp: Attach."
        )

class CodempDeleteBufferCommand(sublime_plugin.WindowCommand):
    def is_enabled(self):
        return len(workspaces.lookup()) > 0

    def run(self, workspace_id, buffer_id):# pyright: ignore[reportIncompatibleMethodOverride]

        try: vws = workspaces.lookupId(workspace_id)
        except KeyError:
            sublime.error_message(f"You are not attached to the workspace '{workspace_id}'")
            logging.warning(f"You are not attached to the workspace '{workspace_id}'")
            return

        if buffer_id in buffers:

            if not sublime.ok_cancel_dialog(
                "You are currently attached to '{buffer_id}'.\n\
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

