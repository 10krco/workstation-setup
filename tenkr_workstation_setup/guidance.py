"""Persistent instructions beside third-party apps in the enrollment session."""
import gi

gi.require_version("Gtk", "4.0")
from gi.repository import GLib, Gtk


class GuidanceWindow(Gtk.Window):
    def __init__(self, application, title, steps, on_return):
        super().__init__(application=application, title="10kR Setup Guide")
        self.set_default_size(340, 600)
        self.set_decorated(False)
        # In the dedicated session reserve the right edge for guidance. Overlay
        # keeps the return button visible even if an external app goes fullscreen.
        import os
        if os.environ.get("TENKR_GUIDED_SESSION") == "1":
            gi.require_version("Gtk4LayerShell", "1.0")
            from gi.repository import Gtk4LayerShell as LayerShell
            if not LayerShell.is_supported():
                raise RuntimeError("The setup session cannot display its instruction panel.")
            LayerShell.init_for_window(self)
            LayerShell.set_namespace(self, "tenkr-setup-guide")
            LayerShell.set_layer(self, LayerShell.Layer.OVERLAY)
            for edge in (LayerShell.Edge.RIGHT, LayerShell.Edge.TOP, LayerShell.Edge.BOTTOM):
                LayerShell.set_anchor(self, edge, True)
            LayerShell.auto_exclusive_zone_enable(self)
            LayerShell.set_keyboard_mode(self, LayerShell.KeyboardMode.ON_DEMAND)

        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=16,
                      margin_top=20, margin_bottom=20, margin_start=20, margin_end=20)
        heading = Gtk.Label(label=title, xalign=0, wrap=True)
        heading.add_css_class("title-2")
        box.append(heading)
        scroll = Gtk.ScrolledWindow(vexpand=True, hscrollbar_policy=Gtk.PolicyType.NEVER)
        instructions = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=18)
        for number, (heading, body) in enumerate(steps, 1):
            label = Gtk.Label(xalign=0, wrap=True, selectable=True, max_width_chars=32)
            label.set_markup(f"<b>{number}. {GLib.markup_escape_text(heading)}</b>\n"
                             + GLib.markup_escape_text(body))
            instructions.append(label)
        scroll.set_child(instructions)
        box.append(scroll)
        button = Gtk.Button(label="Return to setup and check")
        button.add_css_class("suggested-action")
        button.connect("clicked", lambda *_: on_return())
        box.append(button)
        self.set_child(box)
        self.set_focus(button)
