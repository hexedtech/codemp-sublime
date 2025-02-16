import sublime
import logging

from . import qp_globals as qpg

from ..core.workspace import workspaces
# from ..core.buffers import buffers

logger = logging.getLogger(__name__)

def qpi(text, details="", color=qpg.QP_COLOR_NONE, letter="", name="", hint="", prefix=""):
    return sublime.QuickPanelItem(text, details, annotation=hint, kind=(color, letter, name))

def show_qp(window, choices, on_done, placeholder=''):
    def _():
        flags = sublime.KEEP_OPEN_ON_FOCUS_LOST
        window.show_quick_panel(choices, on_done, flags, placeholder=placeholder)
    sublime.set_timeout(_, 10)

class QPServerBrowser():
    def __init__(self, window, host, raw_input_items):
        self.window = window
        self.host = host
        self.raw_input_items = raw_input_items

    def make_entry(self, wsid):
        return qpi(wsid, letter="w", color=qpg.QP_COLOR_BLUISH, hint="Workspace", prefix="    ")

    def qp_placeholder(self):
        return f"Browsing workspaces on host: {self.host}"

    def run(self):
        self.current_wid_selection = None
        self.entries = []
        for item in self.raw_input_items:
            self.entries.append(self.make_entry(item))

        self.entries.insert(0, qpi("Server Actions",
            color=qpg.QP_COLOR_CYANISH,
            letter=qpg.QP_DETAILS,
            hint="Submenu",
            prefix=" • "))

        show_qp(self.window, self.entries, self.server_actions, self.qp_placeholder())

    def server_actions(self, index):
        if index == -1:
            return
        elif index == 0:
            self.edit_server()
            return

        wid = self.entries[index].trigger
        self.current_wid_selection = wid
        # self.select_workspace()
        def _():
            if not wid in workspaces:
                try: self.window.run_command(
                        "codemp_join_workspace", {"workspace_id": wid})
                except Exception as e:
                    return

            ws = workspaces.lookupId(wid)
            buffers = ws.handle.fetch_buffers()

            QPWorkspaceBrowser(self.window, wid, buffers.wait()).run()
        sublime.set_timeout(_)
        logger.debug("exiting the server_broswer.")

    # def select_workspace(self):
    #     assert self.current_wid_selection
    #     actions = [
    #         qpi("Join", details=self.current_wid_selection, color=qpg.QP_COLOR_BLUISH, letter=qpg.QP_FORWARD),
    #         # qpi("Join and open all",
    #         #     details="opens all buffer in the workspace",
    #         #     color=qpg.QP_COLOR_PINKISH, letter=qpg.QP_DETAILS),
    #         qpi("Back", color=qpg.QP_COLOR_BLUISH, letter=qpg.QP_BACK)
    #     ]
    #     show_qp(self.window, actions, self.select_workspace_actions, self.qp_placeholder())

    # def select_workspace_actions(self, index):
    #     if index == -1:
    #         return
    #     elif index == 0:
    #         self.window.run_command(
    #             "codemp_join_workspace",
    #             {"workspace_id": self.current_wid_selection})
    #     elif index == 1:
    #         self.run()


    def edit_server(self):
        actions = [
            qpi("Back", color=qpg.QP_COLOR_CYANISH, letter=qpg.QP_BACK),
            qpi("New Workspace", color=qpg.QP_COLOR_GREENISH, letter=qpg.QP_ADD),
            qpi("Delete Workspace", color=qpg.QP_COLOR_REDISH, letter=qpg.QP_NO)
        ]
        show_qp(self.window, actions, self.edit_server_actions, self.qp_placeholder())

    def edit_server_actions(self, index):
        if index == -1:
            return

        if index == 0:
            self.run()

        if index == 1:
            def create_workspace(name):
                self.window.run_command(
                    "codemp_create_workspace",
                    {"workspace_id": name})
            self.window.show_input_panel("New Workspace Name", "", create_workspace, None, self.edit_server)

        if index == 2:
            def delete_workspace(index):
                if index == -1 or index == 0:
                    self.edit_server()
                # we must be careful here. here with index 1 we are selecting the correct
                # workspace, because the index zero in the entries is the workspace action submenu.
                # which is occupied by the back action.
                # if we add extra non workspace entries, then we must shift the index accordingly.
                # Do this differently?
                selected = self.entries[index]
                self.window.run_command(
                    "codemp_delete_workspace",
                    {"workspace_id": selected.trigger})


            show_qp(self.window, self.entries, delete_workspace, self.qp_placeholder())


class QPWorkspaceBrowser():
    def __init__(self, window, workspace_id, raw_input_items):
        self.window = window
        self.workspace_id = workspace_id
        self.raw_input_items = raw_input_items

    def qp_placeholder(self):
        return f"Browsing buffers in {self.workspace_id}"

    def make_entry(self, item):
        return qpi(item, letter="b", color=qpg.QP_COLOR_BLUISH, hint="Buffer", prefix="    ")

    def run(self):
        self.entries = []
        for buffer in self.raw_input_items:
            self.entries.append(self.make_entry(buffer))

        self.entries.insert(0, qpi("Workspace Actions",
            color=qpg.QP_COLOR_CYANISH,
            letter=qpg.QP_DETAILS,
            hint="Submenu",
            prefix=" • "))

        show_qp(self.window, self.entries, self.workspace_actions, self.qp_placeholder())

    def workspace_actions(self, index):
        if index == -1:
            return
        elif index == 0:
            self.edit_workspace()
            return

        bid = self.entries[index].trigger

        self.window.run_command(
            "codemp_join_buffer",
            {
                "workspace_id": self.workspace_id,
                "buffer_id": bid
            })

    def edit_workspace(self):
        actions = [
            qpi("Back", color=qpg.QP_COLOR_CYANISH, letter=qpg.QP_BACK),
            qpi("Leave Workspace", color=qpg.QP_COLOR_ORANGISH, letter=qpg.QP_BACK),
            qpi("Invite User", color=qpg.QP_COLOR_PINKISH, letter=qpg.QP_FORWARD),
            qpi("Create Buffer", color=qpg.QP_COLOR_GREENISH, letter=qpg.QP_ADD),
            qpi("Delete Buffer", color=qpg.QP_COLOR_REDISH, letter=qpg.QP_NO),
            qpi("Rename Buffer", color=qpg.QP_COLOR_ORANGISH, letter=qpg.QP_RENAME),
        ]
        show_qp(self.window, actions, self.edit_workspace_actions, self.qp_placeholder())

    def edit_workspace_actions(self, index):
        if index == -1 or index == 0:
            self.edit_workspace()
        elif index == 1:
            self.window.run_command(
                "codemp_leave_workspace",
                {"workspace_id": self.workspace_id})
            self.window.run_command(
                "codemp_browse_server", {})
        elif index == 2:
            self.window.run_command(
                "codemp_invite_to_workspace",
                {"workspace_id": self.workspace_id})
        elif index == 3:
            def create_buffer(name):
                self.window.run_command(
                    "codemp_create_buffer",
                    {
                        "workspace_id": self.workspace_id,
                        "buffer_id": name
                    })
            self.window.show_input_panel("New Buffer Name", "", create_buffer, None, self.edit_workspace)
        elif index == 4:
            def delete_buffer(index):
                if index == -1 or index == 0:
                    self.edit_workspace()

                # same warning as the server browser. Check your indexed 3 times
                selected = self.entries[index]
                self.window.run_command(
                    "codemp_delete_buffer",
                    {
                        "workspace_id": self.workspace_id,
                        "buffer_id": selected.trigger
                    })
            show_qp(self.window, self.entries, delete_buffer, self.qp_placeholder())
        elif index == 5:
            sublime.message_dialog("renaming is not yet implemented.")
            self.edit_workspace()