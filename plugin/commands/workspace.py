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


class CodempShareLocalBufferCommand(sublime_plugin.WindowCommand):
    def is_enabled(self) -> bool:
        return workspaces.hasactive()

    def input_description(self) -> str:
        return "Share to workspace:"

    def input(self, args):
        if "workspace_id" not in args:
            return SimpleListInput(
                ("workspace_id", session.client.active_workspaces())
            )

    def run(self, workspace_id: str):
        # get the current active window
        # compute the buffer name:
        #   just the name is alone,
        #   the relative path if in a project
        # check existance:
        #   if existing, ask for overwrite, and beam stuff up
        #   if not, create and then beam stuff up.
        view = self.window.active_view()
        if view:
            self.wid = workspace_id
            self.make_buffer_id(view)

    def make_buffer_id(self, view: sublime.View):
        # if file_name is nothing, then the buffer is not saved to disk,
        # and only has a name.

        isephimeral = view.file_name() is None

        if isephimeral:
            tmpbid = view.name()
            # ask for confirmation of the buffer name.
            self.window.show_input_panel("Share with name:",
                tmpbid,
                lambda str: self.check_validity_and_share(str, view),
                view.set_name,
                lambda: view.set_name(tmpbid))
            return

        windowhasproject = self.window.project_data() is not None
        tmpbid = str(view.file_name())
        if not windowhasproject:
            self.check_validity_and_share(os.path.basename(tmpbid), view)
            return

        projectfolders = self.window.project_data().get("folders") #pyright: ignore
        if not projectfolders:
            self.check_validity_and_share(os.path.basename(tmpbid), view)
            return

        projpaths = [f['path'] for f in projectfolders]
        for projpath in projpaths:
            if os.path.commonpath([projpath]) == os.path.commonpath([projpath, tmpbid]):
                bid = os.path.relpath(tmpbid, projpath)
                self.check_validity_and_share(bid, view)
                return

    def check_validity_and_share(self, bid, view):
        vws = workspaces.lookupId(self.wid)
        if bid in buffers:
            # we are already attached and the buffer exists. Simply send
            # the current contents to the remote.
            bfm = buffers.lookupId(bid)
            bfm.overwrite(TEXT_LISTENER)
            return

        allbuffers = vws.handle.fetch_buffers().wait()
        if bid not in allbuffers:
            # in the future make this creation ephimeral.
            self.window.run_command("codemp_create_buffer", {
                "workspace_id": self.wid,
                "buffer_id": bid
            })

        def _():
            vbuff = some(buffers.register(bid, vws, localview=view))
            vbuff.overwrite(TEXT_LISTENER)

        sublime.set_timeout_async(_)


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

