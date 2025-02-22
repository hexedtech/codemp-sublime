import sublime
import sublime_plugin

import logging

import codemp
from ..core.session import session
from ..core.workspace import workspaces

from ..utils import get_setting
from ..quickpanel.qpbrowser import qpi
from ..quickpanel.qpbrowser import show_qp

from ..input_handlers import SimpleTextInput
from ..input_handlers import SimpleListInput

logger = logging.getLogger(__name__)


def valid_profiles(profiles):
    return [p for p in profiles if "name" in p]


def get_profile_index_by_name(profiles, name):
    return next((index for (index, d) in enumerate(profiles) if d["name"] == name))


def get_default_profile(profiles):
    i = get_profile_index_by_name(profiles, "Default")
    return profiles[i]


class CodempConnectCommand(sublime_plugin.WindowCommand):
    def __init__(self, window):
        super().__init__(window)
        self.connprofile = {}

    def is_enabled(self) -> bool:
        return not session.is_active()

    def update_config_and_connect(self):
        config = codemp.Config(
            username = self.connprofile["username"],
            password = self.connprofile["password"],
            host = self.connprofile["host"],
            port = self.connprofile["port"],
            tls = self.connprofile["tls"]
        )

        session._config = config

        def _():
            try:
                session.connect()
            except Exception as e:
                logger.error(e)
                sublime.error_message(
                    "Could not connect:\n Make sure the server is up\n\
                    and your credentials are correct."
                )
            # If the connect was successfull, save the credentials in memory for the session:
            profiles = get_setting("profiles")
            selected_profile_id = get_profile_index_by_name(profiles, self.connprofile["name"])
            profiles[selected_profile_id] = self.connprofile # pyright: ignore
            sublime.load_settings("Codemp.sublime-settings").set("profiles", profiles)

        sublime.set_timeout_async(_)


    def maybe_get_password(self):
        def __(pwd):
            self.connprofile["password"] = pwd
            self.update_config_and_connect()

        panel = self.window.show_input_panel("Password:", "", __, None, None)
        # Very undocumented feature, the input panel if has the setting 'password' set to true
        # will hide the input.
        panel.settings().set("password", True)

    def maybe_get_user(self):
        def __(usr):
            self.connprofile["username"] = usr
            self.maybe_get_password()

        panel = self.window.show_input_panel("Username:", "", __, None, None)
        panel.settings().set("password", False)

    def run(self):  # pyright: ignore[reportIncompatibleMethodOverride]

        def _run(index):
            profile = profiles[index]
            default_profile = get_default_profile(profiles)
            self.connprofile = {**default_profile, **profile}

            if self.connprofile["username"] and self.connprofile["password"]:
                self.update_config_and_connect()

            if not self.connprofile["username"] and not self.connprofile["password"]:
                self.maybe_get_user()

            if self.connprofile["username"] and not self.connprofile["password"]:
                self.maybe_get_password()

        profiles = valid_profiles(get_setting("profiles"))
        qplist = []
        for p in profiles:
            hint = f"host: {p['host']}:{p['port']}"
            user = p["username"]
            pwd = " : *******" if p["password"] else ""
            details = user + pwd
            qplist.append(qpi(p["name"], details, letter="P", hint=hint))

        show_qp(self.window, qplist, _run, placeholder="Profile")


# Disconnect Command
class CodempDisconnectCommand(sublime_plugin.WindowCommand):
    def is_enabled(self):
        return session.is_active()

    def run(self):
        wslist = session.client.active_workspaces()
        for ws in wslist:
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
                [("workspace_id", wslist)],
            )

    def run(self, workspace_id):  # pyright: ignore[reportIncompatibleMethodOverride]
        if workspace_id in workspaces:
            return

        logger.info(f"Joining workspace: '{workspace_id}'...")
        workspaces.register(workspace_id)


# Leave Workspace Command
class CodempLeaveWorkspaceCommand(sublime_plugin.WindowCommand):
    def is_enabled(self):
        return session.is_active() and workspaces.hasactive()

    def input(self, args):
        if "workspace_id" not in args:
            return SimpleListInput(
                ("workspace_id", session.client.active_workspaces()),
            )

    def run(self, workspace_id: str):  # pyright: ignore[reportIncompatibleMethodOverride]
        if workspace_id not in workspaces:
            sublime.error_message(f"You are not attached to the workspace '{workspace_id}'")
            logger.warning(f"You are not attached to the workspace_id '{workspace_id}'")
            return

        logger.debug("We are about to remove the workspace {}".format(workspace_id))
        workspaces.remove(workspace_id)

class CodempInviteToWorkspaceCommand(sublime_plugin.WindowCommand):
    def is_enabled(self) -> bool:
        return session.is_active() and workspaces.hasactive() > 0

    def input(self, args):
        if "workspace_id" not in args:
            wslist = session.get_workspaces(owned=True, invited=False)
            return SimpleListInput(
                [("workspace_id", wslist), ("user", "invitee's username")]
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

    def run(self, workspace_id: str):  # pyright: ignore[reportIncompatibleMethodOverride]
        try:
            session.client.create_workspace(workspace_id)
        except Exception as e:
            logger.error(f"Could not create workspace: {e}")



class CodempDeleteWorkspaceCommand(sublime_plugin.WindowCommand):
    def is_enabled(self):
        return session.is_active()

    def run(self, workspace_id: str):  # pyright: ignore[reportIncompatibleMethodOverride]
        if workspace_id in workspaces:
            if not sublime.ok_cancel_dialog(
                "You are currently attached to '{workspace_id}'.\n\
                Do you want to detach and delete it?",
                ok_title="yes", title="Delete Workspace?",
            ): return
            self.window.run_command(
                "codemp_leave_workspace",
                {"workspace_id": workspace_id})
        else:
            if not sublime.ok_cancel_dialog(
                f"Confirm you want to delete the workspace '{workspace_id}'",
                ok_title="delete", title="Delete Workspace?",
            ): return

        session.client.delete_workspace(workspace_id).wait()

