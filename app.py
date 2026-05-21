import gi
import tomllib
import subprocess
import json
import cairo
import re
from pathlib import Path
from spellchecker import SpellChecker
gi.require_version("Gtk", "3.0")
gi.require_version("PangoCairo", "1.0")
from gi.repository import Gtk, Gdk, GLib, Gio, Pango, PangoCairo

_spell = SpellChecker()
DEFAULT_FONT_SIZE = 11
FONT_STEP = 2
FONT_MIN = 6
FONT_MAX = 72

CONFIG_PATH = Path(__file__).parent / "config.toml"
NOTES_PATH  = Path(__file__).parent / "notes.json"

TAB_W    = 90
TAB_H    = 30
ADD_W    = 30
BORDER   = 2

def load_config():
    with open(CONFIG_PATH, "rb") as f:
        return tomllib.load(f)

def load_notes():
    if NOTES_PATH.exists():
        data = json.loads(NOTES_PATH.read_text())
        raw = data.get("notes", [""])
        notes = []
        for n in raw:
            if isinstance(n, str):
                notes.append({"text": n, "formats": []})
            else:
                notes.append(n)
        return notes, data.get("active", 0)
    return [{"text": "", "formats": []}], 0

def save_notes(notes, active):
    NOTES_PATH.write_text(json.dumps({"notes": notes, "active": active}))

def derive_name(content, max_len=8):
    first_line = content.strip().split("\n")[0].strip()
    return first_line[:max_len] if first_line else "Untitled"

class TabBar(Gtk.DrawingArea):
    def __init__(self, win_width, on_switch, on_delete, on_new):
        super().__init__()
        self._win_width   = win_width
        self._on_switch   = on_switch
        self._on_delete   = on_delete
        self._on_new      = on_new
        self._names       = []
        self._active      = 0
        self._offset      = 0   # pixel scroll offset

        self.set_size_request(win_width, TAB_H)
        self.set_events(
            Gdk.EventMask.BUTTON_PRESS_MASK |
            Gdk.EventMask.SCROLL_MASK |
            Gdk.EventMask.SMOOTH_SCROLL_MASK
        )
        self.connect("draw", self._draw)
        self.connect("button-press-event", self._on_click)
        self.connect("scroll-event", self._on_scroll)

    # ── public API ──────────────────────────────────────────────────────────

    def set_tabs(self, names, active):
        self._names  = list(names)
        self._active = active
        self._clamp_offset()
        self.queue_draw()

    def set_active(self, idx):
        self._active = idx
        self._ensure_visible(idx)
        self.queue_draw()

    def update_name(self, idx, name):
        if 0 <= idx < len(self._names):
            self._names[idx] = name
            self.queue_draw()

    # ── geometry ────────────────────────────────────────────────────────────

    def _tab_area_width(self):
        return self._win_width - ADD_W

    def _max_offset(self):
        total = len(self._names) * TAB_W
        return max(0, total - self._tab_area_width())

    def _clamp_offset(self):
        self._offset = max(0, min(self._offset, self._max_offset()))

    def _ensure_visible(self, idx):
        x = idx * TAB_W
        area = self._tab_area_width()
        if x < self._offset:
            self._offset = x
        elif x + TAB_W > self._offset + area:
            self._offset = x + TAB_W - area
        self._clamp_offset()

    def _tab_at(self, px):
        area = self._tab_area_width()
        if px >= area:
            return None
        idx = (px + self._offset) // TAB_W
        if 0 <= idx < len(self._names):
            return idx
        return None

    # ── drawing ─────────────────────────────────────────────────────────────

    def _draw(self, _widget, cr):
        area = self._tab_area_width()
        cr.save()
        cr.rectangle(0, 0, area, TAB_H)
        cr.clip()

        for i, name in enumerate(self._names):
            x = i * TAB_W - self._offset
            if x + TAB_W < 0 or x > area:
                continue
            active = (i == self._active)

            # fill
            if active:
                cr.set_source_rgb(1, 1, 1)
            else:
                cr.set_source_rgba(0, 0, 0, 0)
            cr.rectangle(x, 0, TAB_W, TAB_H)
            cr.fill()

            # border
            cr.set_source_rgb(1, 1, 1)
            cr.set_line_width(BORDER)
            cr.rectangle(x + BORDER/2, BORDER/2, TAB_W - BORDER, TAB_H - BORDER)
            cr.stroke()

            # label
            layout = PangoCairo.create_layout(cr)
            layout.set_text(name, -1)
            layout.set_width(Pango.units_from_double(TAB_W - 8))
            layout.set_ellipsize(Pango.EllipsizeMode.END)
            layout.set_alignment(Pango.Alignment.CENTER)
            desc = Pango.FontDescription.from_string("Sans 9")
            layout.set_font_description(desc)
            _, text_rect = layout.get_pixel_extents()
            ty = (TAB_H - text_rect.height) / 2
            cr.move_to(x + 4, ty)
            if active:
                cr.set_source_rgb(0, 0, 0)
            else:
                cr.set_source_rgb(1, 1, 1)
            PangoCairo.show_layout(cr, layout)

        cr.restore()

        # "+" button
        ax = area
        cr.set_source_rgba(0, 0, 0, 0)
        cr.rectangle(ax, 0, ADD_W, TAB_H)
        cr.fill()
        cr.set_source_rgb(1, 1, 1)
        cr.set_line_width(BORDER)
        cr.rectangle(ax + BORDER/2, BORDER/2, ADD_W - BORDER, TAB_H - BORDER)
        cr.stroke()
        cr.set_source_rgb(1, 1, 1)
        cr.select_font_face("Sans", cairo.FONT_SLANT_NORMAL, cairo.FONT_WEIGHT_NORMAL)
        cr.set_font_size(16)
        te = cr.text_extents("+")
        cr.move_to(ax + (ADD_W - te.width) / 2 - te.x_bearing,
                   (TAB_H - te.height) / 2 - te.y_bearing)
        cr.show_text("+")

    # ── events ──────────────────────────────────────────────────────────────

    def _on_click(self, _widget, event):
        area = self._tab_area_width()
        if event.x >= area:
            self._on_new()
            return
        idx = self._tab_at(int(event.x))
        if idx is None:
            return
        if event.type == Gdk.EventType.DOUBLE_BUTTON_PRESS:
            self._on_delete(idx)
        else:
            self._on_switch(idx)

    def _on_scroll(self, _widget, event):
        step = TAB_W
        if event.direction == Gdk.ScrollDirection.SMOOTH:
            _, dx, dy = event.get_scroll_deltas()
            self._offset += int(dy * step)
        elif event.direction in (Gdk.ScrollDirection.DOWN, Gdk.ScrollDirection.RIGHT):
            self._offset += step
        else:
            self._offset -= step
        self._clamp_offset()
        self.queue_draw()
        return True


class FloatingApp(Gtk.ApplicationWindow):
    def __init__(self, app, cfg):
        win = cfg["window"]
        super().__init__(application=app, title=win["title"])
        self._win_width  = win["width"]
        self._win_height = win["height"]
        self.set_default_size(self._win_width, self._win_height)
        self.set_resizable(False)

        self._apply_transparency(win.get("style", {}))

        pos = win.get("position")
        if pos:
            self.connect("realize", self._on_realize, pos, win["title"])

        self.connect("delete-event", self._on_close)

        self._notes_pages  = []
        self._active_idx   = 0
        self._names        = []
        self._spell_timers = {}

        self._tabbar = TabBar(
            self._win_width,
            on_switch=self._switch_to,
            on_delete=self._confirm_delete_tab,
            on_new=lambda: self._add_tab(),
        )

        self._notebook = Gtk.Notebook()
        self._notebook.set_show_tabs(False)
        self._notebook.set_show_border(False)

        separator = Gtk.Separator(orientation=Gtk.Orientation.HORIZONTAL)

        root = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)
        root.pack_start(self._tabbar, False, False, 0)
        root.pack_start(separator, False, False, 0)
        root.pack_start(self._notebook, True, True, 0)
        self.add(root)

        notes, active = load_notes()
        for note in notes:
            self._add_tab(note, switch=False)
        GLib.idle_add(lambda: self._switch_to(active))
        GLib.idle_add(self._rescan_all_on_launch)

    def _add_tab(self, note=None, switch=True):
        if note is None:
            note = {"text": "", "formats": []}
        elif isinstance(note, str):
            note = {"text": note, "formats": []}
        idx = len(self._notes_pages)

        scroll = Gtk.ScrolledWindow()
        scroll.set_policy(Gtk.PolicyType.NEVER, Gtk.PolicyType.AUTOMATIC)

        textview = Gtk.TextView()
        textview.set_wrap_mode(Gtk.WrapMode.WORD_CHAR)
        textview.set_left_margin(12)
        textview.set_right_margin(12)
        textview.set_top_margin(12)
        textview.set_bottom_margin(12)
        buf = textview.get_buffer()
        buf.create_tag("misspelled", underline=Pango.Underline.SINGLE)
        buf.create_tag("bold",   weight=Pango.Weight.BOLD)
        buf.create_tag("italic", style=Pango.Style.ITALIC)
        buf.set_text(note["text"])
        for fmt in note.get("formats", []):
            tag_name = fmt["tag"]
            if tag_name.startswith("size-"):
                try:
                    size = int(tag_name.split("-")[1])
                    tag = self._get_size_tag(buf, size)
                except ValueError:
                    continue
            else:
                tag = buf.get_tag_table().lookup(tag_name)
            if tag:
                buf.apply_tag(tag,
                    buf.get_iter_at_offset(fmt["start"]),
                    buf.get_iter_at_offset(fmt["end"]))
        buf.connect("changed", self._on_content_changed, idx)
        buf.connect("changed", self._on_buf_changed_spell)
        textview.connect("button-press-event", self._on_text_click)
        textview.connect("key-press-event", self._on_key_press)
        scroll.add(textview)
        scroll.show_all()

        self._notebook.append_page(scroll, Gtk.Label())
        self._notes_pages.append((scroll, textview))
        self._names.append(derive_name(note["text"]))
        self._tabbar.set_tabs(self._names, self._active_idx)

        if switch:
            self._switch_to(idx)

    def _on_key_press(self, textview, event):
        if event.state & Gdk.ModifierType.CONTROL_MASK:
            if event.keyval == Gdk.KEY_b:
                self._toggle_format(textview, "bold")
                return True
            elif event.keyval == Gdk.KEY_i:
                self._toggle_format(textview, "italic")
                return True
            elif event.keyval in (Gdk.KEY_plus, Gdk.KEY_equal):
                self._change_font_size(textview, +FONT_STEP)
                return True
            elif event.keyval == Gdk.KEY_minus:
                self._change_font_size(textview, -FONT_STEP)
                return True
        return False

    def _toggle_format(self, textview, tag_name):
        buf = textview.get_buffer()
        bounds = buf.get_selection_bounds()
        if not bounds:
            return
        start, end = bounds
        tag = buf.get_tag_table().lookup(tag_name)
        it = start.copy()
        all_tagged = True
        while it.compare(end) < 0:
            if not it.has_tag(tag):
                all_tagged = False
                break
            it.forward_char()
        if all_tagged:
            buf.remove_tag(tag, start, end)
        else:
            buf.apply_tag(tag, start, end)

    def _get_size_tag(self, buf, size):
        name = f"size-{size}"
        tag = buf.get_tag_table().lookup(name)
        if not tag:
            tag = buf.create_tag(name, size=size * Pango.SCALE)
        return tag

    def _get_selection_size(self, buf, start, end):
        it = start.copy()
        while it.compare(end) < 0:
            for tag in it.get_tags():
                name = tag.get_property("name") or ""
                if name.startswith("size-"):
                    try:
                        return int(name.split("-")[1])
                    except ValueError:
                        pass
            it.forward_char()
        return DEFAULT_FONT_SIZE

    def _remove_size_tags(self, buf, start, end):
        to_remove = []
        buf.get_tag_table().foreach(
            lambda tag: to_remove.append(tag)
            if (tag.get_property("name") or "").startswith("size-") else None
        )
        for tag in to_remove:
            buf.remove_tag(tag, start, end)

    def _change_font_size(self, textview, delta):
        buf = textview.get_buffer()
        bounds = buf.get_selection_bounds()
        if bounds:
            start, end = bounds
        else:
            start = buf.get_start_iter()
            end = buf.get_end_iter()
        current = self._get_selection_size(buf, start, end)
        new_size = max(FONT_MIN, min(FONT_MAX, current + delta))
        self._remove_size_tags(buf, start, end)
        buf.apply_tag(self._get_size_tag(buf, new_size), start, end)

    def _on_text_click(self, textview, event):
        buf = textview.get_buffer()
        tag = buf.get_tag_table().lookup("misspelled")
        if not tag:
            return False
        bx, by = textview.window_to_buffer_coords(Gtk.TextWindowType.WIDGET, int(event.x), int(event.y))
        _, it = textview.get_iter_at_location(bx, by)
        if not it.has_tag(tag):
            return False
        start = it.copy()
        end = it.copy()
        start.backward_word_start()
        end.forward_word_end()
        word = buf.get_text(start, end, False)
        candidates = _spell.candidates(word) or set()
        candidates.discard(word.lower())
        if not candidates:
            return False
        start_off = start.get_offset()
        end_off   = end.get_offset()
        menu = Gtk.Menu()
        for c in sorted(candidates)[:6]:
            item = Gtk.MenuItem(label=c)
            item.connect("activate", self._on_suggestion_pick, textview, start_off, end_off, c)
            menu.append(item)
        menu.show_all()
        menu.popup_at_pointer(event)
        return True

    def _on_suggestion_pick(self, _item, textview, start_off, end_off, replacement):
        buf = textview.get_buffer()
        start = buf.get_iter_at_offset(start_off)
        end   = buf.get_iter_at_offset(end_off)
        format_tags = []
        it = start.copy()
        while it.compare(end) < 0:
            for tag in it.get_tags():
                if (tag.get_property("name") or "") != "misspelled" and tag not in format_tags:
                    format_tags.append(tag)
            it.forward_char()
        buf.delete(start, end)
        buf.insert(buf.get_iter_at_offset(start_off), replacement)
        new_start = buf.get_iter_at_offset(start_off)
        new_end   = buf.get_iter_at_offset(start_off + len(replacement))
        for tag in format_tags:
            buf.apply_tag(tag, new_start, new_end)

    def _on_buf_changed_spell(self, buf):
        if buf in self._spell_timers:
            GLib.source_remove(self._spell_timers[buf])
        self._spell_timers[buf] = GLib.timeout_add(400, self._rescan_spelling, buf)

    def _rescan_all_on_launch(self):
        for _, tv in self._notes_pages:
            self._rescan_spelling(tv.get_buffer())
        return False

    def _rescan_spelling(self, buf):
        self._spell_timers.pop(buf, None)
        tag = buf.get_tag_table().lookup("misspelled")
        if not tag:
            return False
        text = buf.get_text(buf.get_start_iter(), buf.get_end_iter(), False)
        cursor_offset = buf.get_iter_at_mark(buf.get_insert()).get_offset()
        buf.remove_tag(tag, buf.get_start_iter(), buf.get_end_iter())
        for match in re.finditer(r"[a-zA-Z']+", text):
            word = match.group().strip("'")
            if not word:
                continue
            if match.start() <= cursor_offset <= match.end():
                continue
            if word.lower() not in _spell:
                buf.apply_tag(tag,
                    buf.get_iter_at_offset(match.start()),
                    buf.get_iter_at_offset(match.end()))
        return False

    def _switch_to(self, idx):
        n = len(self._notes_pages)
        if n == 0:
            return
        idx = max(0, min(idx, n - 1))
        self._active_idx = idx
        self._notebook.set_current_page(idx)
        self._tabbar.set_active(idx)
        self._notes_pages[idx][1].grab_focus()

    def _on_content_changed(self, buf, idx):
        if idx >= len(self._names):
            return
        content = buf.get_text(buf.get_start_iter(), buf.get_end_iter(), False)
        self._names[idx] = derive_name(content)
        self._tabbar.update_name(idx, self._names[idx])

    def _confirm_delete_tab(self, idx):
        if len(self._notes_pages) == 1:
            return
        dialog = Gtk.MessageDialog(
            transient_for=self,
            modal=True,
            message_type=Gtk.MessageType.QUESTION,
            buttons=Gtk.ButtonsType.YES_NO,
            text="Delete this note?",
        )
        if dialog.run() == Gtk.ResponseType.YES:
            self._notebook.remove_page(idx)
            self._notes_pages.pop(idx)
            self._names.pop(idx)
            self._tabbar.set_tabs(self._names, max(0, idx - 1))
            self._switch_to(max(0, idx - 1))
        dialog.destroy()

    def _collect_notes(self):
        notes = []
        for _, tv in self._notes_pages:
            buf = tv.get_buffer()
            text = buf.get_text(buf.get_start_iter(), buf.get_end_iter(), False)
            formats = []
            size_tags = []
            buf.get_tag_table().foreach(
                lambda t: size_tags.append(t.get_property("name"))
                if (t.get_property("name") or "").startswith("size-") else None
            )
            for tag_name in ("bold", "italic") + tuple(size_tags):
                tag = buf.get_tag_table().lookup(tag_name)
                it = buf.get_start_iter()
                while True:
                    start = it.copy()
                    if not start.forward_to_tag_toggle(tag):
                        break
                    if not start.begins_tag(tag):
                        it = start
                        continue
                    end = start.copy()
                    end.forward_to_tag_toggle(tag)
                    formats.append({"tag": tag_name, "start": start.get_offset(), "end": end.get_offset()})
                    it = end
            notes.append({"text": text, "formats": formats})
        return notes

    def _on_close(self, *_):
        save_notes(self._collect_notes(), self._active_idx)

    def _apply_transparency(self, style):
        opacity = style.get("background_opacity", 1.0)
        screen = self.get_screen()
        css = Gtk.CssProvider()
        css.load_from_data(b"""
            window { background-color: black; }
            * { background-color: transparent; }
            separator { background-color: white; min-height: 2px; }
            textview text selection { background-color: white; color: black; }
        """)
        Gtk.StyleContext.add_provider_for_screen(
            screen, css, Gtk.STYLE_PROVIDER_PRIORITY_APPLICATION
        )
        self.set_property("opacity", opacity)

    def _on_realize(self, _widget, pos, title):
        def move():
            monitors = json.loads(subprocess.check_output(["hyprctl", "monitors", "-j"]))
            focused = next((m for m in monitors if m["focused"]), monitors[0])
            abs_x = focused["x"] + pos["x"]
            abs_y = focused["y"] + pos["y"]
            subprocess.Popen([
                "hyprctl", "dispatch", "movewindowpixel",
                f"exact {abs_x} {abs_y},title:{title}"
            ])
        GLib.timeout_add(50, lambda: (move(), False)[1])


class Application(Gtk.Application):
    def __init__(self):
        super().__init__(
            application_id="com.fastnotes.app",
            flags=Gio.ApplicationFlags.FLAGS_NONE,
        )

    def do_activate(self):
        windows = self.get_windows()
        if windows:
            windows[0].present()
            return
        cfg = load_config()
        win = FloatingApp(self, cfg)
        win.show_all()

if __name__ == "__main__":
    GLib.set_prgname("fast-notes")
    GLib.set_application_name("Fast Notes")
    app = Application()
    app.run()
