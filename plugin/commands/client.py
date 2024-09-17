# pyright: ignore[reportIncompatibleMethodOverride]

import sublime
import sublime_plugin
import logging
import random

from ...lib import codemp
from ..core.session import session
from ..core.registry import workspaces

from input_handlers import SimpleTextInput
from input_handlers import SimpleListInput

logger = logging.getLogger(__name__)

# Client Commands
#############################################################################
# Connect Command
class CodempConnectCommand(sublime_plugin.WindowCommand):
    def is_enabled(self) -> bool:
        return True

    def run(self, server_host, user_name, password):  # pyright: ignore[reportIncompatibleMethodOverride]
        def _():
            try:
                config = codemp.get_default_config()
                config.host = server_host
                config.username = user_name
                config.password = password
                session.connect(config)
            except Exception as e:
                sublime.error_message(
                    "Could not connect:\n Make sure the server is up\n\
                    and your credentials are correct."
                )
        sublime.set_timeout_async(_)

    def input_description(self):
        return "Server host:"

    def input(self, args):
        if "server_host" not in args:
            return SimpleTextInput(
                ("server_host", "http://code.mp:50053"),
                ("user_name", f"user-{random.random()}"),
                ("password", "password?"),
            )

        if "user_name" not in args:
            return SimpleTextInput(
                ("user_name", f"user-{random.random()}"),
                ("password", "password?"),
            )

        if "password" not in args:
            return SimpleTextInput(
                ("password", "password?"),
            )


# Disconnect Command
class CodempDisconnectCommand(sublime_plugin.WindowCommand):
    def is_enabled(self):
        return session.is_active()

    def run(self):
        for ws in workspaces.lookup():
            ws.uninstall()

        session.disconnect()


# Join Workspace Command
class CodempJoinWorkspaceCommand(sublime_plugin.WindowCommand):
    def is_enabled(self) -> bool:
        return client.codemp is not None

    def run(self, workspace_id):  # pyright: ignore[reportIncompatibleMethodOverride]
        assert client.codemp is not None
        if workspace_id is None:
            return

        logger.info(f"Joining workspace: '{workspace_id}'...")
        promise = client.codemp.join_workspace(workspace_id)
        active_window = sublime.active_window()

        def _():
            try:
                workspace = promise.wait()
            except Exception as e:
                logger.error(
                    f"Could not join workspace '{workspace_id}'.\n\nerror: {e}"
                )
                sublime.error_message(f"Could not join workspace '{workspace_id}'")
                return
            client.install_workspace(workspace, active_window)

        sublime.set_timeout_async(_)
        # the else shouldn't really happen, and if it does, it should already be instantiated.
        # ignore.

    def input_description(self):
        return "Join:"

    def input(self, args):
        assert client.codemp is not None
        if "workspace_id" not in args:
            list = client.codemp.list_workspaces(True, True)
            return SimpleListInput(
                ("workspace_id", list.wait()),
            )


# Leave Workspace Command
class CodempLeaveWorkspaceCommand(sublime_plugin.WindowCommand):
    def is_enabled(self):
        return client.codemp is not None and \
        len(client.all_workspaces(self.window)) > 0

    def run(self, workspace_id: str):  # pyright: ignore[reportIncompatibleMethodOverride]
        assert client.codemp is not None
        if client.codemp.leave_workspace(workspace_id):
            vws = client.workspace_from_id(workspace_id)
            if vws is not None:
                client.uninstall_workspace(vws)
        else:
            logger.error(f"could not leave the workspace '{workspace_id}'")

    def input(self, args):
        if "workspace_id" not in args:
            return ActiveWorkspacesIdList()


class CodempInviteToWorkspaceCommand(sublime_plugin.WindowCommand):
    def is_enabled(self) -> bool:
        return client.codemp is not None and len(client.all_workspaces(self.window)) > 0

    def run(self, workspace_id: str, user: str):  # pyright: ignore[reportIncompatibleMethodOverride]
        assert client.codemp is not None
        client.codemp.invite_to_workspace(workspace_id, user)
        logger.debug(f"invite sent to user {user} for workspace {workspace_id}.")

    def input(self, args):
        assert client.codemp is not None
        if "workspace_id" not in args:
            wslist = client.codemp.list_workspaces(True, False)
            return SimpleListInput(
                ("workspace_id", wslist.wait()), ("user", "invitee's username")
            )

        if "user" not in args:
            return SimpleTextInput(("user", "invitee's username"))


class CodempCreateWorkspaceCommand(sublime_plugin.WindowCommand):
    def is_enabled(self):
        return client.codemp is not None

    def run(self, workspace_id: str):  # pyright: ignore[reportIncompatibleMethodOverride]
        assert client.codemp is not None
        client.codemp.create_workspace(workspace_id)

    def input(self, args):
        if "workspace_id" not in args:
            return SimpleTextInput(("workspace_id", "new workspace"))


class CodempDeleteWorkspaceCommand(sublime_plugin.WindowCommand):
    def is_enabled(self):
        return client.codemp is not None

    def run(self, workspace_id: str):  # pyright: ignore[reportIncompatibleMethodOverride]
        assert client.codemp is not None

        vws = client.workspace_from_id(workspace_id)
        if vws is not None:
            if not sublime.ok_cancel_dialog(
                "You are currently attached to '{workspace_id}'.\n\
                Do you want to detach and delete it?",
                ok_title="yes",
                title="Delete Workspace?",
            ):
                return
            if not client.codemp.leave_workspace(workspace_id):
                logger.debug("error while leaving the workspace:")
                raise RuntimeError("error while leaving the workspace")

            client.uninstall_workspace(vws)

        client.codemp.delete_workspace(workspace_id)

    def input(self, args):
        assert client.codemp is not None
        workspaces = client.codemp.list_workspaces(True, False)  # noqa: F841
        if "workspace_id" not in args:
            return SimpleListInput(("workspace_id", workspaces.wait()))
