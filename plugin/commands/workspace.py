import sublime
import sublime_plugin
import logging

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
        return "Attach: "

    def input(self, args):
        if "workspace_id" not in args:
            wslist = session.get_workspaces(owned=True, invited=True)
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
            safe_listener_detach(TEXT_LISTENER)
            safe_listener_attach(TEXT_LISTENER, buff.view.buffer())
            self.window.focus_view(buff.view)
            return
        except KeyError:
            pass

        # # if doesn't exist in the workspace, ask for creation.
        # if vws.handle.get_buffer(buffer_id) is None:
        #     if sublime.ok_cancel_dialog(
        #         f"There is no buffer named '{buffer_id}' in the workspace '{workspace_id}'.\n\
        #         Do you want to create it?",
        #         ok_title="yes", title="Create Buffer?",
        #     ):
        #         sublime.run_command("codemp_create_buffer", {
        #             "workspace_id": workspace_id,
        #             "buffer_id": buffer_id
        #         })

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

            safe_listener_detach(TEXT_LISTENER)
            content_promise = buff_ctl.content()
            vbuff = buffers.add(buff_ctl, vws)

            content = content_promise.wait()
            populate_view(vbuff.view, content)
            if self.window.active_view() == vbuff.view:
                # if view is already active focusing it won't trigger `on_activate`.
                safe_listener_attach(TEXT_LISTENER, vbuff.view.buffer())
            else:
                self.window.focus_view(vbuff.view)
        sublime.set_timeout_async(_)


# Leave Buffer Comand
class CodempLeaveBufferCommand(sublime_plugin.WindowCommand):
    def is_enabled(self):
        return len(buffers.lookup()) > 0

    def input_description(self) -> str:
        return "Leave: "

    def input(self, args):
        if "workspace_id" not in args:
            wslist = session.client.active_workspaces()
            return SimpleListInput(
                ("workspace_id", wslist),
            )

        if "buffer_id" not in args:
            bflist = [bf.id for bf in buffers.lookup(args["workspace_id"])]
            return SimpleListInput(
                ("buffer_id", bflist)
            )

    def run(self, workspace_id, buffer_id): # pyright: ignore[reportIncompatibleMethodOverride]
        try:
            buffers.lookupId(buffer_id)
            vws = workspaces.lookupId(workspace_id)
        except KeyError:
            sublime.error_message(f"You are not attached to the buffer '{buffer_id}'")
            logging.warning(f"You are not attached to the buffer '{buffer_id}'")
            return

        if not vws.handle.get_buffer(buffer_id):
            logging.error("The desired buffer is not managed by the workspace.")
            return

        def _():
            try:
                buffers.remove(buffer_id)
            finally:
                if not vws.handle.detach_buffer(buffer_id):
                    logger.error(f"could not leave the buffer {buffer_id}.")
        sublime.set_timeout_async(_)

# Leave Buffer Comand
class CodempCreateBufferCommand(sublime_plugin.WindowCommand):
    def is_enabled(self):
        return len(workspaces.lookup()) > 0

    def input_description(self) -> str:
        return "Create Buffer: "

    def input(self, args):
        if "workspace_id" not in args:
            wslist = session.client.active_workspaces()
            return SimpleListInput(
                ("workspace_id", wslist),
            )

        if "buffer_id" not in args:
            return SimpleTextInput(
                ("buffer_id", "new buffer name"),
            )

    def run(self, workspace_id, buffer_id):# pyright: ignore[reportIncompatibleMethodOverride]
        try: vws = workspaces.lookupId(workspace_id)
        except KeyError:
            sublime.error_message(
                f"You are not attached to the workspace '{workspace_id}'"
            )
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

    def input_description(self) -> str:
        return "Delete buffer: "

    def input(self, args):
        if "workspace_id" not in args:
            wslist = session.get_workspaces(owned=True, invited=False)
            return SimpleListInput(
                ("workspace_id", wslist),
            )

        if "buffer_id" not in args:
            try: ws = workspaces.lookupId(args["workspace_id"])
            except KeyError:
                sublime.error_message("Workspace does not exists or is not attached.")
                return sublime_plugin.BackInputHandler()

            bflist = ws.handle.fetch_buffers().wait()
            return SimpleListInput(
                ("buffer_id", bflist),
            )

    def run(self, workspace_id, buffer_id):# pyright: ignore[reportIncompatibleMethodOverride]
        try: vws = workspaces.lookupId(workspace_id)
        except KeyError:
            sublime.error_message(
                f"You are not attached to the workspace '{workspace_id}'"
            )
            logging.warning(f"You are not attached to the workspace '{workspace_id}'")
            return

        if not sublime.ok_cancel_dialog(
            f"Confirm you want to delete the buffer '{buffer_id}'",
            ok_title="delete", title="Delete Buffer?",
        ): return

        try:
            buffers.lookupId(buffer_id)
            if not sublime.ok_cancel_dialog(
                "You are currently attached to '{buffer_id}'.\n\
                Do you want to detach and delete it?",
                ok_title="yes", title="Delete Buffer?",
            ):
                return
            self.window.run_command(
                "codemp_leave_buffer",
                { "workspace_id": workspace_id, "buffer_id": buffer_id })
        except KeyError: pass
        finally:
            vws.handle.delete_buffer(buffer_id).wait()
