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
_txt_change_listener = None
_skip_resend = False

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

def get_matching_view(path):
	for window in sublime.windows():
		for view in window.views():
			if view.file_name() == path:
				return view

def rowcol_to_region(view, start, end):
	a = view.text_point(start[0], start[1])
	b = view.text_point(end[0], end[1])
	return sublime.Region(a, b)

def plugin_loaded():
	global _client
	_client = CodempClient() # create an empty instance of the codemp client.
	sublime_asyncio.acquire() # instantiate and start a global asyncio event loop.

def plugin_unloaded():
	global _client
	global _cursor_controller
	global _buffer_controller
	global _txt_change_listener
	for window in sublime.windows():
		for view in window.views():
			if view.settings().get("codemp_buffer", False):
				sublime_asyncio.dispatch(_client.disconnect_buffer(view.file_name()))
				del view.settings()["codemp_buffer"]
				view.erase_regions("codemp_cursors")
	
	if _cursor_controller:
		_cursor_controller.drop_callback()

	if _buffer_controller:
		_buffer_controller.drop_callback()

	if _txt_change_listener:
		if _txt_change_listener.is_attached():
			_txt_change_listener.detach()
		_txt_change_listener = None

	# disconnect the client.
	sublime_asyncio.dispatch(_client.leave_workspace())
	print("unloading")

async def connect_command(server_host, session="default"):
	global _client
	status_log("Connecting to {}".format(server_host))
	await _client.connect(server_host)
	await join_workspace(session)

async def join_workspace(session):
	global _client
	global _cursor_controller

	status_log("Joining workspace: {}".format(session))
	_cursor_controller = await _client.join(session)
	_cursor_controller.callback(move_cursor)

async def share_buffer_command(buffer):
	global _client
	global _cursor_controller
	global _buffer_controller
	global _txt_change_listener

	status_log("Sharing buffer {}".format(buffer))

	view = get_matching_view(buffer)
	contents = get_contents(view)

	try:
		await _client.create(buffer, contents)

		_buffer_controller = await _client.attach(buffer)
		# apply_buffer_change returns a "lambda" that internalises the buffer it is being called on.
		_buffer_controller.callback(apply_buffer_change(view.buffer()))
		
		# we create a new event listener and attach it to the shared buffer.
		_txt_change_listener = CodempClientTextChangeListener()
		_txt_change_listener.attach(view.buffer())
	except Exception as e:
		sublime.error_message("Could not share buffer: {}".format(e))
		return

	view.set_status("z_codemp_buffer", "[Codemp]")
	view.settings()["codemp_buffer"] = True

def move_cursor(cursor_event):
	global _regions_colors

	# TODO: make the matching user/color more solid. now all users have one color cursor.
	# Maybe make all cursors the same color and only use annotations as a discriminant.
	view = get_matching_view(cursor_event.buffer)
	if view.settings().get("codemp_buffer", False):
		reg = rowcol_to_region(view, cursor_event.start, cursor_event.end)
		reg_flags = sublime.RegionFlags.DRAW_EMPTY | sublime.RegionFlags.DRAW_NO_FILL

		view.add_regions(
			"codemp_cursors", 
			[reg], 
			flags = reg_flags, 
			scope=_regions_colors[2], 
			annotations = [cursor_event.user], 
			annotation_color="#000")

def send_cursor(view):
	global _cursor_controller

	path = view.file_name()
	region = view.sel()[0] # TODO: only the last placed cursor/selection.
	start = view.rowcol(region.begin()) #only counts UTF8 chars
	end = view.rowcol(region.end())
	
	_cursor_controller.send(path, start, end)

def send_buffer_change(buffer, changes):
	global _buffer_controller

	view = buffer.primary_view()
	start, txt, end = compress_changes(view, changes)

	# we can't use view.size() since now view has the already modified buffer,
	# but we need to clip wrt the unmodified buffer.
	contlen = len(_buffer_controller.get_content())
	_buffer_controller.delta(max(0, start), txt, min(end, contlen))

	time.sleep(0.1)
	print("server buffer: -------")
	print(_buffer_controller.get_content())

def compress_changes(view, changes):
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

	# as a workaround, whenever we receive multiple changes we compress all of them into a "single one" that delta understands,
	# namely, we get a bounding region to the change, and all the text in between.
	if len(changes) == 1:
		print("[change]", "[", changes[0].a.pt, changes[0].b.pt, "]", changes[0].str)
		return (changes[0].a.pt, changes[0].str, changes[0].b.pt)

	return walk_compress_changes(view, changes)

def walk_compress_changes(view, changes):
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

	txt = view.substr(sublime.Region(txt_a, txt_b))
	print("[walking txt]", "[", txt_a, txt_b, "]", txt)
	print("[walking reg]", "[", reg_a, reg_b, "]")
	return reg_a, txt, reg_b

def apply_buffer_change(buffer):
	status_log("registring callback for buffer: {}".format(buffer.primary_view().file_name()))
	def buffer_callback(text_change):
		global _skip_resend
		# we need to go through a sublime text command, since the method, view.replace
		# needs an edit token, that is obtained only when calling a textcommand associated with a view.
		_skip_resend = True
		view = buffer.primary_view()
		view.run_command("codemp_replace_text",
			{"start": text_change.start_incl,
			 "end": text_change.end_excl,
			 "content": text_change.content})

	return buffer_callback


# Sublime interface
##############################################################################
## WIP ##
# class CodempSublimeBuffer():

# 	def __init__(self, sublime_buffer):
# 		self.buffer = sublime_buffer
# 		self.controller = 
# 		self.listener = CodempClientTextChangeListener()
# 		self.skip_resend = False
# 		self.codemp_callback = apply_buffer_change(sublime_buffer)

# 	def attach_sublime(self):
# 		self.listener.attach(self.buffer)

# 	def detach_sublime(self):
# 		self.listener.detach()
## WIP ##

class CodempClientViewEventListener(sublime_plugin.ViewEventListener):
	@classmethod
	def is_applicable(cls, settings):
		return ("codemp_buffer" in settings)

	@classmethod
	def applies_to_primary_view_only(cls):
		return False

	def on_selection_modified_async(self):
		global _cursor_controller
		if _cursor_controller:
			send_cursor(self.view)

	# def on_text_command(self, command, args):
	# 	global _txt_change_listener
	# 	print(command, args)
	# 	if command == "codemp_replace_text":
	# 		print("detaching listener to :", self.view.file_name())
	# 		_txt_change_listener.detach()

	# 	return None

	# def on_post_text_command(self, command, args):
	# 	global _txt_change_listener
	# 	print(command, args)
	# 	if command == "codemp_replace_text":
	# 		print("reattaching listener to: ", self.view.file_name())
	# 		_text_change_listener.attach(self.view.buffer())

	# 	return None


class CodempClientTextChangeListener(sublime_plugin.TextChangeListener):
	@classmethod
	def is_applicable(cls, buffer):
		# don't attach this event listener automatically
		# we'll do it by hand with .attach(buffer).
		return False

	def on_text_changed_async(self, changes):
		global _buffer_controller
		global _skip_resend
		if _skip_resend:
			_skip_resend = False
			return

		if _buffer_controller:
			send_buffer_change(self.buffer, changes)

class CodempReplaceTextCommand(sublime_plugin.TextCommand):
	def run(self, edit, start, end, content):
		# start included, end excluded
		self.view.replace(edit, sublime.Region(start, end), content)

# See the proxy command class at the bottom
class CodempConnectCommand(sublime_plugin.WindowCommand):
	def run(self, server_host):
		sublime_asyncio.dispatch(connect_command(server_host))

# see proxy command at the bottom
class CodempShareCommand(sublime_plugin.WindowCommand):
	def run(self, buffer):
		sublime_asyncio.dispatch(share_buffer_command(buffer))

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
		return "http://127.0.0.1:50051"