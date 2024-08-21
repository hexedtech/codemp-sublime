import sublime
import sublime_plugin
from Codemp.src import globals as g


def status_log(msg, popup=False):
    sublime.status_message("[codemp] {}".format(msg))
    print("[codemp] {}".format(msg))
    if popup:
        sublime.error_message(msg)


def rowcol_to_region(view, start, end):
    a = view.text_point(start[0], start[1])
    b = view.text_point(end[0], end[1])
    return sublime.Region(a, b)


def safe_listener_detach(txt_listener: sublime_plugin.TextChangeListener):
    if txt_listener is not None and txt_listener.is_attached():
        txt_listener.detach()


def safe_listener_attach(txt_listener: sublime_plugin.TextChangeListener, buffer):
    if txt_listener is not None and not txt_listener.is_attached():
        txt_listener.attach(buffer)


def get_contents(view):
    r = sublime.Region(0, view.size())
    return view.substr(r)


def populate_view(view, content):
    view.run_command(
        "codemp_replace_text",
        {
            "start": 0,
            "end": view.size(),
            "content": content,
            "change_id": view.change_id(),
        },
    )


def get_view_from_local_path(path):
    for window in sublime.windows():
        for view in window.views():
            if view.file_name() == path:
                return view


def draw_cursor_region(view, cursor):
    reg = rowcol_to_region(view, cursor.start, cursor.end)
    reg_flags = sublime.RegionFlags.DRAW_EMPTY

    user_hash = hash(cursor.user)

    def draw():
        view.add_regions(
            f"{g.SUBLIME_REGIONS_PREFIX}-{user_hash}",
            [reg],
            flags=reg_flags,
            scope=g.REGIONS_COLORS[user_hash % len(g.REGIONS_COLORS)],
            annotations=[cursor.user],  # pyright: ignore
            annotation_color=g.PALETTE[user_hash % len(g.PALETTE)],
        )

    sublime.set_timeout_async(draw)
