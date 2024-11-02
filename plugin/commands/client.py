import sublime
import sublime_plugin
import logging
import random

import codemp
from ..core.session import session
from ..core.workspace import workspaces

from ..input_handlers import SimpleTextInput
from ..input_handlers import SimpleListInput

logger = logging.getLogger(__name__)

class CodempConnectCommand(sublime_plugin.WindowCommand):
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

    def input_description(self):
        return "Server host:"

    def run(self, server_host, user_name, password):  # pyright: ignore[reportIncompatibleMethodOverride]
        def _():
            try:
                config = codemp.Config(
                    username = user_name,
                    password = password,
                    host = server_host,
                    port=50053,
                    tls=False)
                session.connect(config)
            except Exception as e:
                logger.error(e)
                sublime.error_message(
                    "Could not connect:\n Make sure the server is up\n\
                    and your credentials are correct."
                )
        sublime.set_timeout_async(_)

# Disconnect Command
class CodempDisconnectCommand(sublime_plugin.WindowCommand):
    def is_enabled(self):
        return session.is_active()

    def run(self):
        cli = session.client

        for ws in workspaces.lookup():
            if cli.leave_workspace(ws.id):
                workspaces.remove(ws)

        session.drop_client()
        logger.info(f"disconnected from server '{session.config.host}'!")


# Join Workspace Command
class CodempJoinWorkspaceCommand(sublime_plugin.WindowCommand):
    def is_enabled(self) -> bool:
        return session.is_active()

    def input_description(self):
        return "Join:"

    def input(self, args):
        if "workspace_id" not in args:
            wslist = session.get_workspaces()
            return SimpleListInput(
                ("workspace_id", wslist),
            )

    def run(self, workspace_id):  # pyright: ignore[reportIncompatibleMethodOverride]
        if workspace_id is None:
            return

        logger.info(f"Joining workspace: '{workspace_id}'...")
        try:
            ws = session.client.attach_workspace(workspace_id).wait()
        except Exception as e:
            logger.error(f"Could not join workspace '{workspace_id}': {e}")
            sublime.error_message(f"Could not join workspace '{workspace_id}'")
            return

        logger.debug("Joined! Adding workspace to registry")
        workspaces.add(ws)


# Leave Workspace Command
class CodempLeaveWorkspaceCommand(sublime_plugin.WindowCommand):
    def is_enabled(self):
        return session.is_active() and \
        len(workspaces.lookup(self.window)) > 0

    def input(self, args):
        if "workspace_id" not in args:
            wslist = session.client.active_workspaces()
            return SimpleListInput(
                ("workspace_id", wslist),
            )

    def run(self, workspace_id: str):  # pyright: ignore[reportIncompatibleMethodOverride]
        try:
            workspaces.remove(workspace_id)
        finally:
            if not session.client.leave_workspace(workspace_id):
                logger.error(f"could not leave the workspace '{workspace_id}'")


class CodempInviteToWorkspaceCommand(sublime_plugin.WindowCommand):
    def is_enabled(self) -> bool:
        return session.is_active() and len(workspaces.lookup(self.window)) > 0

    def input(self, args):
        if "workspace_id" not in args:
            wslist = session.get_workspaces(owned=True, invited=False)
            return SimpleListInput(
                ("workspace_id", wslist), ("user", "invitee's username")
            )

        if "user" not in args:
            return SimpleTextInput(("user", "invitee's username"))

    def run(self, workspace_id: str, user: str):  # pyright: ignore[reportIncompatibleMethodOverride]
        try:
            session.client.invite_to_workspace(workspace_id, user)
            logger.debug(f"invite sent to user {user} for workspace {workspace_id}.")
        except Exception as e:
            logger.error(f"Could not invite to workspace: {e}")



class CodempCreateWorkspaceCommand(sublime_plugin.WindowCommand):
    def is_enabled(self):
        return session.is_active()

    def input(self, args):
        if "workspace_id" not in args:
            return SimpleTextInput(("workspace_id", "new workspace name"))

    def run(self, workspace_id: str):  # pyright: ignore[reportIncompatibleMethodOverride]
        try:
            session.client.create_workspace(workspace_id)
        except Exception as e:
            logger.error(f"Could not create workspace: {e}")



class CodempDeleteWorkspaceCommand(sublime_plugin.WindowCommand):
    def is_enabled(self):
        return session.is_active()

    def input(self, args):
        workspaces = session.get_workspaces(owned=True, invited=False)  # noqa: F841
        if "workspace_id" not in args:
            return SimpleListInput(("workspace_id", workspaces)

    def run(self, workspace_id: str):  # pyright: ignore[reportIncompatibleMethodOverride]
        try:
            vws = workspaces.lookupId(workspace_id)
            if not sublime.ok_cancel_dialog(
                "You are currently attached to '{workspace_id}'.\n\
                Do you want to detach and delete it?",
                ok_title="yes", title="Delete Workspace?",
            ):
                return
            self.window.run_command(
                "codemp_leave_workspace",
                {"workspace_id": workspace_id})

        except KeyError: pass
        finally:
            session.client.delete_workspace(workspace_id)

