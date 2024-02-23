import sublime
import sublime_plugin


def status_log(msg):
    sublime.status_message("[codemp] {}".format(msg))
    print("[codemp] {}".format(msg))


def rowcol_to_region(view, start, end):
    a = view.text_point(start[0], start[1])
    b = view.text_point(end[0], end[1])
    return sublime.Region(a, b)


def is_active(view):
    if view.window().active_view() == view:
        return True
    return False


def safe_listener_detach(txt_listener: sublime_plugin.TextChangeListener):
    if txt_listener.is_attached():
        txt_listener.detach()
