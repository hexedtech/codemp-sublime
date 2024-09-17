import sublime_plugin
import logging

from typing import Tuple, Union, List

# Input handlers
############################################################
class SimpleTextInput(sublime_plugin.TextInputHandler):
    def __init__(self, *args: Tuple[str, Union[str, List[str]]]):
        logging.debug(f"why isn't the text input working? {args}")
        self.argname = args[0][0]
        self.default = args[0][1]
        self.next_inputs = args[1:]

    def initial_text(self):
        if isinstance(self.default, str):
            return self.default
        else:
            return ""

    def name(self):
        return self.argname

    def next_input(self, args):
        if len(self.next_inputs) > 0:
            if self.next_inputs[0][0] not in args:
                if isinstance(self.next_inputs[0][1], list):
                    return SimpleListInput(*self.next_inputs)
                else:
                    return SimpleTextInput(*self.next_inputs)


class SimpleListInput(sublime_plugin.ListInputHandler):
    def __init__(self, *args: Tuple[str, Union["list[str]", str]]):
        self.argname = args[0][0]
        self.list = args[0][1]
        self.next_inputs = args[1:]

    def name(self):
        return self.argname

    def list_items(self):
        if isinstance(self.list, list):
            return self.list
        else:
            return [self.list]

    def next_input(self, args):
        if len(self.next_inputs) > 0:
            if self.next_inputs[0][0] not in args:
                if isinstance(self.next_inputs[0][1], str):
                    return SimpleTextInput(*self.next_inputs)
                else:
                    return SimpleListInput(*self.next_inputs)


# class ActiveWorkspacesIdList(sublime_plugin.ListInputHandler):
#     def __init__(self, window=None, buffer_list=False, buffer_text=False):
#         self.window = window
#         self.buffer_list = buffer_list
#         self.buffer_text = buffer_text

#     def name(self):
#         return "workspace_id"

#     def list_items(self):
#         return [vws.id for vws in client.all_workspaces(self.window)]

#     def next_input(self, args):
#         if self.buffer_list:
#             return BufferIdList(args["workspace_id"])
#         elif self.buffer_text:
#             return SimpleTextInput(("buffer_id", "new buffer"))


# # To allow for having a selection and choosing non existing workspaces
# # we do a little dance: We pass this list input handler to a TextInputHandler
# # when we select "Create New..." which adds his result to the list of possible
# # workspaces and pop itself off the stack to go back to the list handler.
# class WorkspaceIdList(sublime_plugin.ListInputHandler):
#     def __init__(self):
#         assert client.codemp is not None  # the command should not be available

#         # at the moment, the client can't give us a full list of existing workspaces
#         # so a textinputhandler would be more appropriate. but we keep this for the future

#         self.add_entry_text = "* add entry..."
#         self.list = client.codemp.list_workspaces(True, True).wait()
#         self.list.sort()
#         self.list.append(self.add_entry_text)
#         self.preselected = None

#     def name(self):
#         return "workspace_id"

#     def placeholder(self):
#         return "Workspace"

#     def list_items(self):
#         if self.preselected is not None:
#             return (self.list, self.preselected)
#         else:
#             return self.list

#     def next_input(self, args):
#         if args["workspace_id"] == self.add_entry_text:
#             return AddListEntry(self)


# class BufferIdList(sublime_plugin.ListInputHandler):
#     def __init__(self, workspace_id):
#         vws = client.workspace_from_id(workspace_id)
#         self.add_entry_text = "* create new..."
#         self.list = vws.codemp.filetree(None)
#         self.list.sort()
#         self.list.append(self.add_entry_text)
#         self.preselected = None

#     def name(self):
#         return "buffer_id"

#     def placeholder(self):
#         return "Buffer Id"

#     def list_items(self):
#         if self.preselected is not None:
#             return (self.list, self.preselected)
#         else:
#             return self.list

#     def next_input(self, args):
#         if args["buffer_id"] == self.add_entry_text:
#             return AddListEntry(self)


class AddListEntry(sublime_plugin.TextInputHandler):
    # this class works when the list input handler
    # added appended a new element to it's list that will need to be
    # replaced with the entry added from here!
    def __init__(self, list_input_handler):
        self.parent = list_input_handler

    def name(self):
        return ""

    def validate(self, text: str) -> bool:
        return not len(text) == 0

    def confirm(self, text: str):
        self.parent.list.pop()  # removes the add_entry_text
        self.parent.list.insert(0, text)
        self.parent.preselected = 0

    def next_input(self, args):
        return sublime_plugin.BackInputHandler()
