import sublime
import sublime_plugin
import logging

from .src.client import client
from listeners import TEXT_LISTENER
from input_handlers import SimpleTextInput
from input_handlers import ActiveWorkspacesIdList
from input_handlers import BufferIdList

logger = logging.getLogger(__name__)

# Join Buffer Command
class CodempJoinBufferCommand(sublime_plugin.WindowCommand):
    def is_enabled(self):
        available_workspaces = client.all_workspaces(self.window)
        return len(available_workspaces) > 0

    def run(self, workspace_id, buffer_id): # pyright: ignore[reportIncompatibleMethodOverride]
        # A workspace has some Buffers inside of it (filetree)
        # some of those you are already attached to
        # If already attached to it return the same alredy existing bufferctl
        # if existing but not attached (attach)
        # if not existing ask for creation (create + attach)
        vws = client.workspace_from_id(workspace_id)
        assert vws is not None

        # is the buffer already installed?
        if buffer_id in vws.codemp.buffer_list():
            logger.info("buffer already installed!")
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
        logger.debug(f"attempting to attach to {buffer_id}...")
        promise = vws.codemp.attach(buffer_id)

        def deferred_attach(promise):
            try:
                buff_ctl = promise.wait()
                logger.debug("attach successfull!")
            except Exception as e:
                logging.error(f"error when attaching to buffer '{id}':\n\n {e}")
                sublime.error_message(f"Could not attach to buffer '{buffer_id}'")
                return

            vbuff = vws.install_buffer(buff_ctl, TEXT_LISTENER)
            client.register_buffer(vws, vbuff)  # we need to keep track of it.

            # TODO! if the view is already active calling focus_view()
            # will not trigger the on_activate
            self.window.focus_view(vbuff.view)

        sublime.set_timeout_async(lambda: deferred_attach(promise))

    def input_description(self) -> str:
        return "Attach: "

    def input(self, args):
        if "workspace_id" not in args:
            return ActiveWorkspacesIdList(self.window, buffer_list=True)

        if "buffer_id" not in args:
            return BufferIdList(args["workspace_id"])


# Leave Buffer Comand
class CodempLeaveBufferCommand(sublime_plugin.WindowCommand):
    def is_enabled(self):
        return len(client.all_buffers()) > 0

    def run(self, workspace_id, buffer_id): # pyright: ignore[reportIncompatibleMethodOverride]
        vbuff = client.buffer_from_id(buffer_id)
        vws = client.workspace_from_id(workspace_id)

        if vbuff is None or vws is None:
            sublime.error_message(f"You are not attached to the buffer '{id}'")
            logging.warning(f"You are not attached to the buffer '{id}'")
            return

        def defer_detach():
            if vws.codemp.detach(buffer_id):
                vws.uninstall_buffer(vbuff)
                client.unregister_buffer(vbuff)

        sublime.set_timeout_async(defer_detach)

    def input_description(self) -> str:
        return "Leave: "

    def input(self, args):
        if "workspace_id" not in args:
            return ActiveWorkspacesIdList(self.window, buffer_list=True)

        if "buffer_id" not in args:
            return BufferIdList(args["workspace_id"])


# Leave Buffer Comand
class CodempCreateBufferCommand(sublime_plugin.WindowCommand):
    def is_enabled(self):
        return len(client.all_workspaces(self.window)) > 0

    def run(self, workspace_id, buffer_id):# pyright: ignore[reportIncompatibleMethodOverride]
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
            return ActiveWorkspacesIdList(self.window, buffer_text=True)

        if "buffer_id" not in args:
            return SimpleTextInput(
                (("buffer_id", "new buffer")),
            )


class CodempDeleteBufferCommand(sublime_plugin.WindowCommand):
    def is_enabled(self):
        return client.codemp is not None and len(client.codemp.active_workspaces()) > 0

    def run(self, workspace_id, buffer_id):# pyright: ignore[reportIncompatibleMethodOverride]
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
                logging.error(
                    f"error when deleting the buffer '{buffer_id}':\n\n {e}", True
                )
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
            return ActiveWorkspacesIdList(self.window, buffer_list=True)

        if "buffer_id" not in args:
            return BufferIdList(args["workspace_id"])
