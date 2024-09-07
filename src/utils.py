import sublime
import sublime_plugin
from typing import Dict, Generic, TypeVar
from . import globals as g

# bidirectional dictionary so that we can have bidirectional
# lookup!
# In particular we can use it for:
# bd[workspace_id] = window
# bd[view] = virtual_buffer

D = TypeVar("D", Dict, dict)
K = TypeVar("K")
V = TypeVar("V")


# using del bd.inverse[key] doesn't work since it can't be intercepted.
# the only way is to iterate:
# for key in bd.inverse[inverse_key]
class bidict(dict, Generic[K, V]):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.inverse: Dict[V, list[K]] = {}

        for key, value in self.items():
            self.inverse.setdefault(value, []).append(key)

    def __setitem__(self, key: K, value: V):
        if key in self:
            self.inverse[self[key]].remove(key)
        super(bidict, self).__setitem__(key, value)
        self.inverse.setdefault(value, []).append(key)

    def __delitem__(self, key: K):
        # if we delete a normal key, remove the key from the inverse element.
        inverse_key = self[key]
        self.inverse.setdefault(inverse_key, []).remove(key)

        # if the resulting inverse key list is empty delete it
        if inverse_key in self.inverse and not self.inverse[inverse_key]:
            del self.inverse[inverse_key]

        # delete the normal key
        super(bidict, self).__delitem__(key)

    def inverse_del(self, inverse_key: V):
        # deletes all the elements matching the inverse key
        # the last del will also delete the inverse key.
        for key in self.inverse[inverse_key]:
            self.pop(key, None)

    def clear(self):
        self.inverse.clear()
        super(bidict, self).clear()


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


def draw_cursor_region(view, start, end, user):
    reg = rowcol_to_region(view, start, end)
    reg_flags = sublime.RegionFlags.DRAW_EMPTY

    user_hash = hash(user)

    view.add_regions(
        f"{g.SUBLIME_REGIONS_PREFIX}-{user_hash}",
        [reg],
        flags=reg_flags,
        scope=g.REGIONS_COLORS[user_hash % len(g.REGIONS_COLORS)],
        annotations=[user],  # pyright: ignore
        annotation_color=g.PALETTE[user_hash % len(g.PALETTE)],
    )
