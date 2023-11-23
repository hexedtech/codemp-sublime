import sublime
import sublime_plugin

# import Codemp.codemp_client as codemp
from Codemp.src.codemp_client import *
import Codemp.ext.sublime_asyncio as sublime_asyncio
import asyncio
import os
import time

# UGLYYYY, find a way to not have global variables laying around.
_tasks = []
_buffers = []
_client = None
_cursor_controller = None
_txt_change_listener = None
_exit_handler_id = None

_regions_colors = [
	"region.redish",
	"region.orangeish",
	"region.yellowish",
	"region.greenish",
	"region.cyanish",
	"region.bluish",
	"region.purplish",
	"region.pinkish"
]

## Initialisation and Deinitialisation
##############################################################################

async def disconnect_client():
	global _client
	global _cursor_controller
	global _buffers
	global _txt_change_listener
	global _tasks
	status_log("disconnecting...")

	# buffers clean up after themselves after detaching
	for buff in _buffers:
		await buff.detach(_client)

	for task in _tasks:
		task.cancel()

	if _cursor_controller:
		await _client.leave_workspace()

	if _txt_change_listener:
		safe_listener_detach(_txt_change_listener)

def plugin_loaded():
	global _client
	global _txt_change_listener
	global _exit_handler_id
	_client = CodempClient() # create an empty instance of the codemp client.
	_txt_change_listener = CodempClientTextChangeListener() # instantiate the listener to attach around.
	
	# instantiate and start a global asyncio event loop.
	# pass in the exit_handler coroutine that will be called upon relasing the event loop.
	_exit_handler_id = sublime_asyncio.acquire(disconnect_client) 
	status_log("plugin loaded")

def plugin_unloaded():
	sublime_asyncio.release(False, _exit_handler_id)
	# disconnect the client.
	status_log("unloading")



## Utils ##
##############################################################################
def status_log(msg):
	sublime.status_message("[codemp] {}".format(msg))
	print("[codemp] {}".format(msg))

def store_task(name = None):
	def store_named_task(task):
		global _tasks
		task.set_name(name)
		_tasks.append(task)

	return store_named_task

def get_contents(view):
	r = sublime.Region(0, view.size())
	return view.substr(r)

def populate_view(view, content):
	view.run_command("codemp_replace_text", {
		"start": 0,
		"end": view.size(),
		"content": content,
		"change_id": view.change_id(),
	})

def get_view_from_local_path(path):
	for window in sublime.windows():
		for view in window.views():
			if view.file_name() == path:
				return view

def rowcol_to_region(view, start, end):
	a = view.text_point(start[0], start[1])
	b = view.text_point(end[0], end[1])
	return sublime.Region(a, b)

def get_buffer_from_buffer_id(buffer_id):
	global _buffers
	for b in _buffers:
		if b.view.buffer_id() == buffer_id:
			return b

def get_buffer_from_remote_name(remote_name):
	global _buffers
	for b in _buffers:
		if b.remote_name == remote_name:
			return b

def is_active(view):
	if view.window().active_view() == view:
		return True
	return False

def safe_listener_detach(txt_listener):
	if txt_listener.is_attached():
		txt_listener.detach()

## Main logic (build coroutines to be dispatched through sublime_asyncio)
# Connection command
##############################################################################

async def connect_command(server_host, session):
	global _client
	status_log("Connecting to {}".format(server_host))
	await _client.connect(server_host)
	await join_workspace(session)

# Workspace and cursor (attaching, sending and receiving)
##############################################################################
async def join_workspace(session):
	global _client
	global _cursor_controller

	status_log("Joining workspace: {}".format(session))
	_cursor_controller = await _client.join(session)
	sublime_asyncio.dispatch(move_cursor(_cursor_controller), store_task("move-cursor"))

async def move_cursor(cursor_controller):
	global _regions_colors

	status_log("spinning up cursor worker...")
	# TODO: make the matching user/color more solid. now all users have one color cursor.
	# Maybe make all cursors the same color and only use annotations as a discriminant.
	# idea: use a user id hash map that maps to a color.
	try:
		while cursor_event := await cursor_controller.recv():
			buffer = get_buffer_from_remote_name(cursor_event.buffer)

			if buffer:
				reg = rowcol_to_region(buffer.view, cursor_event.start, cursor_event.end)
				reg_flags = sublime.RegionFlags.DRAW_EMPTY | sublime.RegionFlags.DRAW_NO_FILL

				buffer.view.add_regions(
					"codemp_cursors", 
					[reg], 
					flags = reg_flags, 
					scope=_regions_colors[hash(cursor_event.user) % len(_regions_colors)], 
					annotations = [cursor_event.user], 
					annotation_color="#000")

	except asyncio.CancelledError:
	    status_log("cursor worker stopped...")

def send_cursor(view):
	global _cursor_controller

	buffer_name = get_buffer_from_buffer_id(view.buffer_id()).remote_name
	region = view.sel()[0] # TODO: only the last placed cursor/selection.
	start = view.rowcol(region.begin()) #only counts UTF8 chars
	end = view.rowcol(region.end())
	
	_cursor_controller.send(buffer_name, start, end)

# Buffer Controller (managing text modifications)
##############################################################################

# This class is used as an abstraction between the local buffers (sublime side) and the
# remote buffers (codemp side), to handle the syncronicity.
class CodempSublimeBuffer():
	def __init__(self, view, remote_name):
		self.view = view
		self.remote_name = remote_name
		self.worker_task_name = "buffer-worker-{}".format(self.remote_name)

	async def attach(self, client):
		global _txt_change_listener

		status_log("attaching local buffer '{}' to '{}'".format(self.view.file_name(), self.remote_name))
		# attach to the matching codemp buffer
		self.controller = await client.attach(self.remote_name)

		# if the view is already active calling focus_view() will not trigger the on_activate()
		if is_active(self.view):
			status_log("\tattaching text listener...")
			safe_listener_detach(_txt_change_listener)
			_txt_change_listener.attach(self.view.buffer())
		else:
			self.view.window().focus_view(self.view)
		
		# start the buffer worker that waits for text_changes in the worker thread
		sublime_asyncio.dispatch(self.apply_buffer_change(), store_task(self.worker_task_name))
		
		# mark all views associated with the buffer as being connected to codemp
		for v in self.view.buffer().views():
			v.set_status("z_codemp_buffer", "[Codemp]")
			v.settings()["codemp_buffer"] = True

	async def detach(self, client):
		global _txt_change_listener
		global _tasks
		global _buffers
		status_log("detaching buffer '{}' ({})".format(self.remote_name, self.view.file_name()))
		
		if is_active(self.view):
			safe_listener_detach(_txt_change_listener)

		await client.disconnect_buffer(self.remote_name)

		# take down the worker task
		for task in _tasks:
			if task.get_name() == self.worker_task_name:
				task.cancel()
				_tasks.remove(task)
				break

		# remove yourself from the _buffers
		_buffers.remove(self)

		# clean up all the stuff we left around
		for v in self.view.buffer().views():
			del v.settings()["codemp_buffer"]
			v.erase_status("z_codemp_buffer")
			v.erase_regions("codemp_cursors")

	async def apply_buffer_change(self):
		global _txt_change_listener
		status_log("spinning up '{}' buffer worker...".format(self.remote_name))
		try:
			while text_change := await self.controller.recv():
				# In case a change arrives to a background buffer, just apply it. We are not listening on it.
				# Otherwise, interrupt the listening to avoid echoing back the change just received.
				status_log("recieved txt change: ")
				active = is_active(self.view)
				if active:
					safe_listener_detach(_txt_change_listener)

				# we need to go through a sublime text command, since the method, view.replace
				# needs an edit token, that is obtained only when calling a textcommand associated with a view.
				self.view.run_command("codemp_replace_text", {
					"start": text_change.start_incl,
					"end": text_change.end_excl,
					"content": text_change.content,
					"change_id": self.view.change_id()
				})

				if active:
					_txt_change_listener.attach(self.view.buffer())
		except asyncio.CancelledError:
		    status_log("'{}' buffer worker stopped...".format(self.remote_name))

	def send_buffer_change(self, changes):
		# Sublime text on_text_changed events, gives a list of changes.
		# in case of simple insertion or deletion this is fine.
		# but if we swap a string (select it and add another string in it's place) or have multiple selections
		# or do an undo of some kind after the just mentioned events we receive multiple split text changes, 
		# e.g. select the world `hello` and replace it with `12345`: Sublime will separate it into two singular changes,
		# first add `12345` in front of `hello`: `12345hello` then, delete the `hello`.
		# The gotcha here is that now we have an issue of indexing inside the buffer. when adding `12345` we shifted the index of the
		# start of the word `hello` to the right by 5.
		# By sending these changes one by one generated some buffer length issues in delta, since we have an interdependency of the
		# changes.

		# if the historic region is empty, we are inserting.
		# if it isn't we are deleting.
		for change in changes:
			region = sublime.Region(change.a.pt, change.b.pt)
			status_log("sending txt change: Reg({} {}) -> '{}'".format(region.begin(), region.end(), change.str))
			self.controller.send(region.begin(), region.end(), change.str)

		# as a workaround, whenever we receive multiple changes we compress all of them into a "single one" that delta understands,
		# namely, we get a bounding region to the change, and all the text in between.
		# if len(changes) == 1:
		# 	region = self.view.transform_region_from(sublime.Region(changes[0].a.pt, changes[0].b.pt), self.old_change_id)
		# 	txt = changes[0].str
		# else:
		# 	start, end = compress_change_region(changes)
		# 	region = self.view.transform_region_from(sublime.Region(start, end), self.old_change_id)
		# 	txt = view.substr(region)

		# self.controller.send(region.begin(), region.end(), txt)

def compress_change_region(changes):
	# the bounding region of all text changes.
	txt_a = float("inf")
	txt_b = 0

	# the region in the original buffer subjected to the change.
	reg_a = float("inf")
	reg_b = 0

	# we keep track of how much the changes move the indexing of the buffer
	buffer_shift = 0 # left - + right

	for change in changes:
		# the change in characters that the change would bring
		# len(str) and .len_utf8 are mutually exclusive
		# len(str) is when we insert new text at a position
		# .len_utf8 is the length of the deleted/canceled string in the buffer
		change_delta = len(change.str) - change.len_utf8

		# the text region is enlarged to the left
		txt_a = min(txt_a, change.a.pt)

		# On insertion, change.b.pt == change.a.pt
		# 	If we meet a new insertion further than the current window
		# 	we expand to the right by that change.
		# On deletion, change.a.pt == change.b.pt - change.len_utf8
		# 	when we delete a selection and it is further than the current window
		# 	we enlarge to the right up until the begin of the deleted region.
		if change.b.pt > txt_b:
			txt_b = change.b.pt + change_delta
		else:
			# otherwise we just shift the window according to the change
			txt_b += change_delta

		# the bounding region enlarged to the left
		reg_a = min(reg_a, change.a.pt)

		# In this bit, we want to look at the buffer BEFORE the modifications
		# but we are working on the buffer modified by all previous changes for each loop
		# we use buffer_shift to keep track of how the buffer shifts around
		# to map back to the correct index for each change in the unmodified buffer.
		if change.b.pt + buffer_shift > reg_b:
			# we only enlarge if we have changes that exceede on the right the current window
			reg_b = change.b.pt + buffer_shift

		# after using the change delta, we archive it for the next iterations
		# the minus is just for being able to "add" the buffer shift with a +.
		# since we encode deleted text as negative in the change_delta, but that requires the shift to the
		# old position to be positive, and viceversa for text insertion.
		buffer_shift -= change_delta

		# print("\t[buff change]", change.a.pt, change.str, "(", change.len_utf8,")", change.b.pt)

	# print("[walking txt]", "[", txt_a, txt_b, "]", txt)
	# print("[walking reg]", "[", reg_a, reg_b, "]")
	return reg_a, reg_b


# we call this command manually to have access to the edit token.
class CodempReplaceTextCommand(sublime_plugin.TextCommand):
	def run(self, edit, start, end, content, change_id):
		# we modify the region to account for any change that happened in the mean time
		region = self.view.transform_region_from(sublime.Region(start, end), change_id)
		self.view.replace(edit, region, content)

async def join_buffer_command(view, remote_name):
	global _client
	global _buffers

	try:
		buffer = CodempSublimeBuffer(view, remote_name)
		await buffer.attach(_client)
		_buffers.append(buffer)

		## we should receive all contents from the server upon joining.
	except Exception as e:
		sublime.error_message("Could not join buffer: {}".format(e))
		return

async def share_buffer_command(buffer_path, remote_name = "test"):
	global _client
	global _buffers

	view = get_view_from_local_path(buffer_path)
	contents = get_contents(view)

	try:
		await _client.create(remote_name, contents)
		await join_buffer_command(view, remote_name)
	except Exception as e:
		sublime.error_message("Could not share buffer: {}".format(e))
		return

async def disconnect_buffer_command(buffer):
	global _client
	await buffer.detach(_client)

# Listeners
##############################################################################

class CodempClientViewEventListener(sublime_plugin.ViewEventListener):
	@classmethod
	def is_applicable(cls, settings):
		return settings.get("codemp_buffer", False)

	@classmethod
	def applies_to_primary_view_only(cls):
		return False

	def on_selection_modified_async(self):
		send_cursor(self.view)

	# We only edit on one view at a time, therefore we only need one TextChangeListener
	# Each time we focus a view to write on it, we first attach the listener to that buffer.
	# When we defocus, we detach it.
	def on_activated(self):
		global _txt_change_listener
		print("view {} activated".format(self.view.id()))
		_txt_change_listener.attach(self.view.buffer())

	def on_deactivated(self):
		global _txt_change_listener
		print("view {} deactivated".format(self.view.id()))
		safe_listener_detach(_txt_change_listener)


class CodempClientTextChangeListener(sublime_plugin.TextChangeListener):
	@classmethod
	def is_applicable(cls, buffer):
		# don't attach this event listener automatically
		# we'll do it by hand with .attach(buffer).
		return False

	# lets make this blocking :D
	# def on_text_changed_async(self, changes):
	def on_text_changed(self, changes):
		subl_buffer = get_buffer_from_buffer_id(self.buffer.id())
		subl_buffer.send_buffer_change(changes)


# Commands:
# 	codemp_connect: 	connect to a server.
# 	codemp_join: 		join a workspace with a given name within the server.
#	codemp_share: 		shares a buffer with a given name in the workspace.
#
# Internal commands:
#	replace_text: swaps the content of a view with the given text.
#
# Connect Command
#############################################################################
class CodempConnectCommand(sublime_plugin.WindowCommand):
	def run(self, server_host, session):
		sublime_asyncio.dispatch(connect_command(server_host, session))

	def input(self, args):
		if 'server_host' not in args:
			return ServerHostInputHandler()

	def input_description(self):
		return 'Server host:'

class ServerHostInputHandler(sublime_plugin.TextInputHandler):
	def initial_text(self):
		return "http://127.0.0.1:50051"

	def next_input(self, args):
		if 'workspace' not in args:
			return CodempWorkspaceInputHandler()

class CodempWorkspaceInputHandler(sublime_plugin.TextInputHandler):
	def name(self):
		return 'session'
	def initial_text(self):
		return "default"



# Join Command
#############################################################################
class CodempJoinCommand(sublime_plugin.WindowCommand):
	def run(self, server_buffer):
		view = self.window.new_file(flags=sublime.NewFileFlags.TRANSIENT)
		sublime_asyncio.dispatch(join_buffer_command(view, server_buffer))
	
	def input_description(self):
		return 'Join Buffer:'

	def input(self, args):
		if 'server_buffer' not in args:
			return ServerBufferInputHandler()

class ServerBufferInputHandler(sublime_plugin.TextInputHandler):
	def initial_text(self):
		return "What buffer should I join?"


# Share Command
#############################################################################
class CodempShareCommand(sublime_plugin.WindowCommand):
	def run(self, sublime_buffer_path, server_id):
		sublime_asyncio.dispatch(share_buffer_command(sublime_buffer_path, server_id))
	
	def input(self, args):
		if 'sublime_buffer' not in args:
			return SublimeBufferPathInputHandler()

	def input_description(self):
		return 'Share Buffer:'

class SublimeBufferPathInputHandler(sublime_plugin.ListInputHandler):
	def list_items(self):
		ret_list = []

		for window in sublime.windows():
			for view in window.views():
				if view.file_name():
					ret_list.append(view.file_name())

		return ret_list

	def next_input(self, args):
		if 'server_id' not in args:
			return ServerIdInputHandler()

class ServerIdInputHandler(sublime_plugin.TextInputHandler):
	def initial_text(self):
		return "Buffer name on server"

# Disconnect Buffer Command
#############################################################################
class CodempDisconnectBufferCommand(sublime_plugin.WindowCommand):
	def run(self, remote_name):
		buffer = get_buffer_from_remote_name(remote_name)
		sublime_asyncio.dispatch(disconnect_buffer_command(buffer))
	
	def input(self, args):
		if 'remote_name' not in args:
			return RemoteNameInputHandler()

	def input_description(self):
		return 'Disconnect Buffer:'

class RemoteNameInputHandler(sublime_plugin.ListInputHandler):
	def list_items(self):
		global _buffers
		ret_list = []

		for buff in _buffers:
			ret_list.append(buff.remote_name)

		return ret_list

# Proxy Commands ( NOT USED )
#############################################################################
# class ProxyCodempShareCommand(sublime_plugin.WindowCommand):
# 	# on_window_command, does not trigger when called from the command palette
# 	# See: https://github.com/sublimehq/sublime_text/issues/2234 
# 	def run(self, **kwargs):
# 		self.window.run_command("codemp_share", kwargs)
#
# 	def input(self, args):
# 		if 'sublime_buffer' not in args:
# 			return SublimeBufferPathInputHandler()
#
# 	def input_description(self):
# 		return 'Share Buffer:'
#
# class ProxyCodempJoinCommand(sublime_plugin.WindowCommand):
# 	def run(self, **kwargs):
# 		self.window.run_command("codemp_join", kwargs)
#
# 	def input(self, args):
# 		if 'server_buffer' not in args:
# 			return ServerBufferInputHandler()
#
# 	def input_description(self):
# 		return 'Join Buffer:'
#
# class ProxyCodempConnectCommand(sublime_plugin.WindowCommand):
# 	# on_window_command, does not trigger when called from the command palette
# 	# See: https://github.com/sublimehq/sublime_text/issues/2234 
# 	def run(self, **kwargs):
# 		self.window.run_command("codemp_connect", kwargs)
#
# 	def input(self, args):
# 		if 'server_host' not in args:
# 			return ServerHostInputHandler()
#
# 	def input_description(self):
# 		return 'Server host:'
