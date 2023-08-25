import sublime
import sublime_plugin

# import Codemp.codemp_client as codemp
from Codemp.src.codemp_client import *
import Codemp.ext.sublime_asyncio as sublime_asyncio
import asyncio
import time

# UGLYYYY, find a way to not have global variables laying around.
_tasks = []
_client = None
_cursor_controller = None
_buffer_controller = None
_setting_key = "codemp_buffer"

def store_task(name = None):
	def store_named_task(task):
		global _tasks
		task.set_name(name)
		_tasks.append(task)

	return store_named_task

def plugin_loaded():
	global _client
	_client = CodempClient()
	sublime_asyncio.acquire() # instantiate and start a global event loop.

class CodempClientViewEventListener(sublime_plugin.ViewEventListener):
	@classmethod
	def is_applicable(cls, settings):
		return "codemp_buffer" in settings

	def on_selection_modified_async(self):
		global _cursor_controller
		if _cursor_controller:
			sublime_asyncio.dispatch(send_selection(self.view))

	def on_close(self):
		self.view.settings()["codemp_buffer"] = False

class CodempClientTextChangeListener(sublime_plugin.TextChangeListener):
	@classmethod
	def is_applicable(cls, buffer):
		for view in buffer.views():
			if "codemp_buffer" in view.settings():
				return True
		return False

	def on_text_changed(self, changes):
		global _buffer_controller
		if _buffer_controller:
			for change in changes:
				sublime_asyncio.dispatch(apply_changes(change))

async def apply_changes(change):
	global _buffer_controller

	text = change.str
	skip = change.a.pt
	if change.len_utf8 == 0: # we are inserting new text.
		tail = len(_buffer_controller.get_content()) - skip
	else: # we are changing an existing region of text of length len_utf8
		tail = len(_buffer_controller.get_content()) - skip - change.len_utf8

	tail_skip = len(_buffer_controller.get_content()) - tail
	print("[buff change]", skip, text, tail_skip)
	await _buffer_controller.apply(skip, text, tail)

async def make_connection(server_host):
	global _client

	if _client.ready:
		sublime.message_dialog("A connection already exists.")
		return

	sublime.status_message("[codemp] Connecting to {}".format(server_host))
	print("[codemp] Connecting to {}".format(server_host))
	await _client.connect(server_host)

	id = await _client.get_id()
	sublime.status_message("[codemp] Connected with client ID: {}".format(id))
	print("[codemp] Connected with client ID: ", id)

async def move_cursor(usr, caller, path, start, end):
	print(usr, caller, start, end)

async def sync_buffer(caller, start, end, txt):
	print("[buffer]", caller, start, end, txt)

async def share_buffer(buffer):
	global _client
	global _cursor_controller
	global _buffer_controller

	if not _client.ready:
		sublime.error_message("No connected client.")
		return

	sublime.status_message("[codemp] Sharing buffer {}".format(buffer))
	print("[codemp] Sharing buffer {}".format(buffer))

	view = get_matching_view(buffer)
	contents = get_contents(view)
	created = await _client.create(view.file_name(), contents)
	if not created:
		sublime.error_message("Could not share buffer.")
		return

	_buffer_controller = await _client.attach(buffer)
	_buffer_controller.callback(sync_buffer, _client.id)
	
	_cursor_controller = await _client.listen()
	_cursor_controller.callback(move_cursor, _client.id)

	if not _cursor_controller:
		sublime.error_message("Could not subsribe a listener.")
		return
	if not _buffer_controller:
		sublime.error_message("Could not attach to the buffer.")
		return

	sublime.status_message("[codemp] Listening")
	print("[codemp] Listening")

	view.settings()["codemp_buffer"] = True

async def join_buffer(window, buffer):
	global _client
	global _cursor_controller
	global _buffer_controller

	if not _client.ready:
		sublime.error_message("No connected client.")
		return

	view = get_matching_view(buffer)

	sublime.status_message("[codemp] Joining buffer {}".format(buffer))
	print("[codemp] Joining buffer {}".format(buffer))

	_buffer_controller = await _client.attach(buffer)
	content = _buffer_controller.get_content()
	view.run_command("codemp_replace_view", {"content": content})

	_cursor_controller = await _client.listen()
	_cursor_controller.callback(move_cursor)
	

	if not _cursor_controller:
		sublime.error_message("Could not subsribe a listener.")
		return
	if not _buffer_controller:
		sublime.error_message("Could not attach to the buffer.")
		return

	sublime.status_message("[codemp] Listening")
	print("[codemp] Listening")

	view.settings()["codemp_buffer"] = True

async def send_selection(view):
	global _cursor_controller

	path = view.file_name()
	region = view.sel()[0] # TODO: only the last placed cursor/selection.
	start = view.rowcol(region.begin()) #only counts UTF8 chars
	end = view.rowcol(region.end())
	
	await _cursor_controller.send(path, start, end)

def get_contents(view):
	r = sublime.Region(0, view.size())
	return view.substr(r)

def get_matching_view(path):
	for window in sublime.windows():
		for view in window.views():
			if view.file_name() == path:
				return view


# See the proxy command class at the bottom
class CodempConnectCommand(sublime_plugin.WindowCommand):
	def run(self, server_host):
		sublime_asyncio.dispatch(make_connection(server_host))

# see proxy command at the bottom
class CodempShareCommand(sublime_plugin.WindowCommand):
	def run(self, buffer):
		sublime_asyncio.dispatch(share_buffer(buffer))

# see proxy command at the bottom
class CodempJoinCommand(sublime_plugin.WindowCommand):
	def run(self, buffer):
		sublime_asyncio.dispatch(join_buffer(self.window, buffer))

class CodempPopulateView(sublime_plugin.TextCommand):
	def run(self, edit, content):
		self.view.replace(edit, sublime.Region(0, self.view.size()), content)

class ProxyCodempConnectCommand(sublime_plugin.WindowCommand):
	# on_window_command, does not trigger when called from the command palette
	# See: https://github.com/sublimehq/sublime_text/issues/2234 
	def run(self, **kwargs):
		self.window.run_command("codemp_connect", kwargs)

	def input(self, args):
		if 'server_host' not in args:
			return ServerHostInputHandler()

	def input_description(self):
		return 'Server host:'

class ProxyCodempShareCommand(sublime_plugin.WindowCommand):
	# on_window_command, does not trigger when called from the command palette
	# See: https://github.com/sublimehq/sublime_text/issues/2234 
	def run(self, **kwargs):
		self.window.run_command("codemp_share", kwargs)

	def input(self, args):
		if 'buffer' not in args:
			return BufferInputHandler()

	def input_description(self):
		return 'Share Buffer:'


class ProxyCodempJoinCommand(sublime_plugin.WindowCommand):
	# on_window_command, does not trigger when called from the command palette
	# See: https://github.com/sublimehq/sublime_text/issues/2234 
	def run(self, **kwargs):
		self.window.run_command("codemp_join", kwargs)

	def input(self, args):
		if 'buffer' not in args:
			return BufferInputHandler()

	def input_description(self):
		return 'Join Buffer:'

class BufferInputHandler(sublime_plugin.ListInputHandler):
	def list_items(self):
		ret_list = []

		for window in sublime.windows():
			for view in window.views():
				if view.file_name():
					ret_list.append(view.file_name())

		return ret_list

class ServerHostInputHandler(sublime_plugin.TextInputHandler):
	def initial_text(self):
		return "http://[::1]:50051"