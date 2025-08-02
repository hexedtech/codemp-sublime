import sublime
import sublime_plugin
import logging
import os

import codemp

from .utils import get_setting

def ensure_get_output_panel():
	panel = sublime.active_window().find_output_panel("codemp_log")
	if not panel:
		panel = sublime.active_window().create_output_panel("codemp_log")

	return panel

class CodempToggleLogPanelCommand(sublime_plugin.WindowCommand):
	def run(self):
		panel = ensure_get_output_panel()
		panel.set_read_only(True)
		activepanel = self.window.active_panel()

		if activepanel or activepanel != "output.codemp_log":
			self.window.run_command("show_panel", {"panel": "output.codemp_log"})
		else:
			self.window.run_command("hide_panel", {})
			
class CodempLogMessageCommand(sublime_plugin.TextCommand):
	def run(self, edit: sublime.Edit, text: str):
		self.view.set_read_only(False)
		print("the panel has ", self.view.size(), " elements")
		self.view.insert(edit, self.view.size(), text + '\n')
		self.view.set_read_only(True)

class SublimePanelHandler(logging.Handler):
	def __init__(self, level=logging.NOTSET):
		super().__init__(level)

	def emit(self, record):
		panel = ensure_get_output_panel()
		if self.formatter:
			msg = self.formatter.format(record)
			print(msg)
			# This currently hangs, when called from the callback...
			# sublime.set_timeout_async(lambda: panel.run_command("codemp_log_message", {"text": msg}), 10)

class CodempLogger():
	def __init__(self, root, level) -> None:
		self.level = level
		self.pkg_logger = logging.getLogger(root)
		self.pkg_logger.setLevel(self.level)
		self.pkg_logger.propagate = False
		self.formatter = logging.Formatter(
			fmt="{levelname} <{asctime}> ({threadName}) [{name}::{funcName}:{lineno}] {message}",
			style="{",
		)

		self.filehandler = logging.FileHandler(self.get_logfile(), "w")
		self.filehandler.setFormatter(self.formatter)
		self.panelhandler = SublimePanelHandler()
		self.panelhandler.setFormatter(self.formatter)

		self.pkg_logger.debug("registering logger callback...")
		if not codemp.set_logger(self.codemp_log_cb, False):
			self.pkg_logger.debug("could not register the logger... \
				If reconnecting it's ok, the previous logger is still registered"
			)

	def codemp_log_cb(self, msg):
		sublime.set_timeout_async(lambda: self.pkg_logger.debug(msg), 10)

	def default_logfile(self):
		cachedir = os.path.join(sublime.cache_path(), "Codemp")
		os.makedirs(cachedir, exist_ok=True)
		return os.path.join(cachedir, "codemp.log")

	def get_logfile(self):
		logfromsettings = get_setting("logfile")
		if not logfromsettings:
			logfromsettings = self.default_logfile()
		logfilename = str(logfromsettings)
		logfilename = os.path.expanduser(logfilename)
		logfilename = os.path.abspath(logfilename)
		return logfilename

	def enable_logging(self):
		self.pkg_logger.addHandler(self.filehandler)
		self.pkg_logger.addHandler(self.panelhandler)

	def disenable_logging(self):
		self.pkg_logger.removeHandler(self.filehandler)
		self.pkg_logger.removeHandler(self.panelhandler)

