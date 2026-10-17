# Main Hovir window.

import os
import threading

import gi
gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")
from gi.repository import Adw, Gio, GLib, Gtk

from babel import Locale, UnknownLocaleError

from .audio import AudioRouter
from .engines import ENGINES
from .settings import Settings
from .voices import Voice, VoiceCatalog


def _voice_factory(icon=False):
    factory = Gtk.SignalListItemFactory()

    def setup(_factory, item):
        box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
        image = Gtk.Image()
        label = Gtk.Label(xalign=0, hexpand=True, ellipsize=3)
        box.append(image)
        box.append(label)
        item.set_child(box)

    def bind(_factory, item):
        value = item.get_item().get_string()
        icon_name, label = value.split("|", 1)
        item.get_child().get_first_child().set_from_icon_name(icon_name if icon else "")
        item.get_child().get_last_child().set_text(label)

    factory.connect("setup", setup)
    factory.connect("bind", bind)
    return factory


@Gtk.Template(resource_path="/io/github/trunar/Hovir/window.ui")
class HovirWindow(Adw.ApplicationWindow):
    __gtype_name__ = "HovirWindow"

    engine_dropdown = Gtk.Template.Child()
    language_dropdown = Gtk.Template.Child()
    voice_dropdown = Gtk.Template.Child()
    devices_dropdown = Gtk.Template.Child()
    hear_switch = Gtk.Template.Child()
    text_scroller = Gtk.Template.Child()
    text_view = Gtk.Template.Child()
    text_placeholder = Gtk.Template.Child()
    speak_button = Gtk.Template.Child()
    voice_size_label = Gtk.Template.Child()
    progress_bar = Gtk.Template.Child()

    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self.settings = Settings()
        self.catalog = VoiceCatalog(GLib.get_user_data_dir())
        self.audio = AudioRouter()
        self.sink_name = None
        self.voices = []
        self._device_names = [None]
        self._suppress_device_notify = False
        self._busy = False
        self._downloading = False
        self._suppress_language_notify = False
        self._voice_load_generation = 0

        self.engine_dropdown.set_model(Gtk.StringList.new(["Piper"]))
        self.engine_dropdown.set_selected(0)
        self.settings.set("engine", "piper")
        self._suppress_engine_notify = False
        self.engine_dropdown.connect("notify::selected", self._on_engine_selected)
        self.language_dropdown.connect("notify::selected", self._on_language_selected)
        self.voice_dropdown.connect("notify::selected", self._on_voice_selected)
        self.devices_dropdown.connect("notify::selected", self._on_device_selected)
        self.speak_button.connect("clicked", self._on_speak_clicked)
        self.hear_switch.set_active(self.settings.get("hear-myself"))
        self.hear_switch.connect("notify::active", self._on_hear_changed)
        self.voice_dropdown.set_factory(_voice_factory(icon=True))
        self.voice_dropdown.set_list_factory(_voice_factory(icon=True))

        self.text_view.get_buffer().connect("changed", self._on_text_changed)
        self._on_text_changed(self.text_view.get_buffer())
        speak_action = Gio.SimpleAction.new("speak", None)
        speak_action.connect("activate", lambda *_args: self._on_speak_clicked(self.speak_button))
        self.add_action(speak_action)
        app = self.get_application()
        if app:
            app.set_accels_for_action("win.speak", ["Return", "KP_Enter"])
        self._load_catalog_and_audio()

    def _status(self, message):
        if message and any(word in message.lower() for word in ("failed", "unavailable", "could not", "no voice")):
            self.speak_button.set_tooltip_text(message)
        else:
            self._update_speak_tooltip()

    def _update_speak_tooltip(self):
        index = self.voice_dropdown.get_selected()
        if index < len(self.voices) and self.catalog.installed(self.voices[index]):
            self.speak_button.set_tooltip_text("Speak text (Enter)")
        else:
            self.speak_button.set_tooltip_text("Download selected voice")

    def _on_engine_selected(self, dropdown, _pspec):
        if self._suppress_engine_notify:
            return
        selected = dropdown.get_selected()
        self.settings.set("engine", "piper" if selected == 0 else "")

    def _on_text_changed(self, buffer):
        self.text_placeholder.set_visible(buffer.get_char_count() == 0)

    def _thread(self, func, done, failed=None):
        def run():
            try:
                value = func()
                GLib.idle_add(done, value)
            except Exception as error:
                GLib.idle_add(failed or self._show_error, error)
        threading.Thread(target=run, daemon=True).start()

    def open_voice_manager(self):
        dialog = Adw.Window(
            transient_for=self,
            modal=True,
            title="Manage Downloaded Voices",
            default_width=480,
            default_height=480,
        )
        toolbar = Adw.ToolbarView()
        header = Adw.HeaderBar()
        toolbar.add_top_bar(header)

        body = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=12)
        body.set_margin_top(18)
        body.set_margin_bottom(18)
        body.set_margin_start(18)
        body.set_margin_end(18)
        bulk_delete = Gtk.Button(label="Delete All Downloaded Voices")
        bulk_delete.add_css_class("destructive-action")
        bulk_delete.set_halign(Gtk.Align.CENTER)
        list_box = Gtk.ListBox()
        list_box.add_css_class("boxed-list")
        bulk_delete.connect("clicked", lambda *_args: self._confirm_delete_all(dialog, list_box, bulk_delete))
        body.append(bulk_delete)
        scroll = Gtk.ScrolledWindow()
        scroll.set_vexpand(True)
        scroll.set_child(list_box)
        body.append(scroll)
        toolbar.set_content(body)
        dialog.set_content(toolbar)
        self._voice_manager_window = dialog
        self._populate_voice_manager(list_box, bulk_delete)
        dialog.present()

    def _populate_voice_manager(self, list_box, bulk_delete):
        while child := list_box.get_first_child():
            list_box.remove(child)
        voices = self.catalog.list_installed()
        bulk_delete.set_sensitive(bool(voices))
        if not voices:
            row = Adw.ActionRow(title="No downloaded voices")
            row.set_subtitle("Downloaded voices will appear here.")
            list_box.append(row)
            return
        for voice in voices:
            row = Adw.ActionRow(title=voice.name)
            row.set_subtitle(voice.path)
            delete_button = Gtk.Button(label="Delete")
            delete_button.add_css_class("destructive-action")
            delete_button.set_valign(Gtk.Align.CENTER)
            delete_button.connect("clicked", self._delete_managed_voice, list_box, bulk_delete, voice)
            row.add_suffix(delete_button)
            list_box.append(row)

    def _delete_managed_voice(self, _button, list_box, bulk_delete, voice):
        confirm = Adw.AlertDialog(
            heading=f"Delete {voice.name}?",
            body="This removes the downloaded voice files from Hovir. You can download this voice again later.",
        )
        confirm.add_response("cancel", "Cancel")
        confirm.add_response("delete", "Delete")
        confirm.set_response_appearance("delete", Adw.ResponseAppearance.DESTRUCTIVE)
        confirm.set_default_response("cancel")
        confirm.set_close_response("cancel")

        def response(_dialog, choice):
            if choice == "delete":
                self.catalog.delete_voice(voice)
                self._refresh_selected_voice()
                self._populate_voice_manager(list_box, bulk_delete)

        confirm.connect("response", response)
        confirm.present(self._voice_manager_window)

    def _confirm_delete_all(self, parent, list_box, bulk_delete):
        dialog = Adw.AlertDialog(
            heading="Delete all downloaded voices?",
            body="This removes all voice models stored by Hovir. They can be downloaded again later.",
        )
        dialog.add_response("cancel", "Cancel")
        dialog.add_response("delete", "Delete All")
        dialog.set_response_appearance("delete", Adw.ResponseAppearance.DESTRUCTIVE)
        dialog.set_default_response("cancel")
        dialog.set_close_response("cancel")

        def response(_dialog, choice):
            if choice == "delete":
                self.catalog.delete_all()
                self._refresh_selected_voice()
                self._populate_voice_manager(list_box, bulk_delete)

        dialog.connect("response", response)
        dialog.present(parent)

    def _refresh_selected_voice(self):
        self._render_voices()

    def _show_error(self, error):
        self._status(str(error))
        return False

    def _load_catalog_and_audio(self):
        self._status("Connecting to audio and loading languages…")

        def work():
            try:
                sink = self.audio.ensure_sink()
                devices = self.audio.devices()
                audio_error = None
            except Exception as error:
                sink, devices, audio_error = None, [], str(error)
            try:
                languages = self.catalog.list_languages()
                catalog_error = None
            except Exception as error:
                languages, catalog_error = [], str(error)
            return sink, devices, languages, catalog_error, audio_error

        def done(value):
            sink, devices, languages, catalog_error, audio_error = value
            self.sink_name = sink
            self._populate_devices(devices)
            self._populate_languages(languages)
            if audio_error:
                self._status(f"Audio setup unavailable: {audio_error}")
            elif catalog_error:
                self._status(f"Voice catalog unavailable: {catalog_error}. Installed voices remain available.")
            elif not languages:
                self._status("No voice languages were returned by Hugging Face.")
            else:
                self._status("")
            self._load_installed_if_catalog_empty()
            return False

        self._thread(work, done)

    def _populate_languages(self, languages):
        preferred = self.settings.get("language")
        names = [self._language_name(language) for language in languages]
        self._suppress_language_notify = True
        self.language_dropdown.set_model(Gtk.StringList.new(names))
        if not names:
            self._suppress_language_notify = False
            return
        index = languages.index(preferred) if preferred in languages else 0
        self._languages = languages
        self.language_dropdown.set_selected(index)
        self._suppress_language_notify = False
        self.settings.set("language", languages[index])
        self._load_voices(languages[index])

    @staticmethod
    def _language_name(code):
        try:
            return Locale.parse(code).get_language_name()
        except (UnknownLocaleError, ValueError):
            return code.upper()

    def _load_installed_if_catalog_empty(self):
        if hasattr(self, "_languages") and self._languages:
            return
        found = []
        for path in self.catalog.voice_dir.rglob("*.onnx"):
            if not os.path.isfile(str(path) + ".json"):
                continue
            relative = path.relative_to(self.catalog.voice_dir).as_posix()
            code = relative.split("/", 1)[0]
            found.append((code, Voice(path.stem, relative)))
        if found:
            languages = sorted({code for code, _voice in found})
            self._languages = languages
            self._suppress_language_notify = True
            self.language_dropdown.set_model(Gtk.StringList.new([self._language_name(code) for code in languages]))
            self.language_dropdown.set_selected(0)
            self._suppress_language_notify = False
            self.voices = [voice for code, voice in found if code == languages[0]]
            self._render_voices()
        else:
            self.voices = []
            self._render_voices()

    def _on_language_selected(self, dropdown, _pspec):
        if self._suppress_language_notify or not hasattr(self, "_languages") or not self._languages:
            return
        selected = dropdown.get_selected()
        if selected >= len(self._languages):
            return
        language = self._languages[selected]
        self.settings.set("language", language)
        self._load_voices(language)

    def _load_voices(self, language):
        self._voice_load_generation += 1
        generation = self._voice_load_generation
        self._status(f"Loading {language.upper()} voices…")

        def done(voices):
            if generation != self._voice_load_generation:
                return False
            self.voices = voices
            self._render_voices()
            self._status("")
            return False

        def failed(error):
            if generation != self._voice_load_generation:
                return False
            self.voices = self._installed_for(language)
            self._render_voices()
            self._status(f"Could not load the online catalog: {error}. Showing installed voices.")
            return False

        self._thread(lambda: self.catalog.list_voices(language), done, failed)

    def _installed_for(self, language):
        installed = []
        for path in self.catalog.voice_dir.rglob("*.onnx"):
            if not os.path.isfile(str(path) + ".json"):
                continue
            relative = path.relative_to(self.catalog.voice_dir).as_posix()
            if relative.split("/", 1)[0] == language:
                installed.append(Voice(path.stem, relative))
        return sorted(installed, key=lambda voice: voice.name)

    def _render_voices(self):
        preferred = self.settings.get("voice")
        rows = []
        for voice in self.voices:
            installed = self.catalog.installed(voice)
            rows.append(("object-select-symbolic" if installed else "folder-download-symbolic") + "|" + voice.name)
        self.voice_dropdown.set_model(Gtk.StringList.new(rows))
        if not rows:
            self.voice_size_label.set_text("")
            self.speak_button.set_sensitive(False)
            self._update_speak_tooltip()
            return
        selected = next((index for index, voice in enumerate(self.voices) if voice.name == preferred), 0)
        self.voice_dropdown.set_selected(selected)
        self.speak_button.set_sensitive(True)

    def _on_voice_selected(self, dropdown, _pspec):
        index = dropdown.get_selected()
        if index >= len(self.voices):
            return
        voice = self.voices[index]
        self.settings.set("voice", voice.name)
        installed = self.catalog.installed(voice)
        size = f" · {voice.size / 1_000_000:.0f} MB" if voice.size else ""
        self.voice_size_label.set_text(size.strip(" ·"))
        self.voice_size_label.set_visible(not installed and bool(voice.size))
        self.speak_button.set_label("Speak" if installed else "Download voice")
        self._update_speak_tooltip()

    def _populate_devices(self, devices):
        stored = self.settings.get("additional-devices")
        self._device_names = [None]
        labels = ["None"]
        for name, label in devices:
            if name == self.sink_name:
                continue
            self._device_names.append(name)
            labels.append(label)
        selected = next((index for index, name in enumerate(self._device_names)
                         if name is not None and name in stored), 0)
        self._suppress_device_notify = True
        self.devices_dropdown.set_model(Gtk.StringList.new(labels))
        self.devices_dropdown.set_selected(selected)
        self._suppress_device_notify = False
        self.settings.set("additional-devices", [self._device_names[selected]] if selected else [])

    def _on_device_selected(self, dropdown, _pspec):
        if self._suppress_device_notify:
            return
        index = dropdown.get_selected()
        name = self._device_names[index] if index < len(self._device_names) else None
        self.settings.set("additional-devices", [name] if name else [])

    def _on_hear_changed(self, switch, _pspec):
        self.settings.set("hear-myself", switch.get_active())

    def _on_remove_sink(self, _button):
        dialog = Adw.AlertDialog(
            heading="Remove Hovir virtual audio sink?",
            body="Apps using this virtual audio sink will lose the device until Hovir creates it again.",
        )
        dialog.add_response("cancel", "Cancel")
        dialog.add_response("remove", "Remove")
        dialog.set_response_appearance("remove", Adw.ResponseAppearance.DESTRUCTIVE)
        dialog.set_default_response("cancel")
        dialog.set_close_response("cancel")
        dialog.connect("response", self._remove_sink_response)
        dialog.present(self)

    def request_remove_sink(self):
        self._on_remove_sink(None)

    def _remove_sink_response(self, _dialog, response):
        if response != "remove":
            return
        def done(count):
            self.sink_name = None
            self._status("Hovir virtual audio sink removed. It will be recreated the next time you speak.")
            return False
        self._thread(self.audio.remove_hovir_sinks, done)

    def _on_speak_clicked(self, _button):
        if self._busy:
            return
        index = self.voice_dropdown.get_selected()
        if index >= len(self.voices):
            self._status("Choose an available voice first.")
            return
        voice = self.voices[index]
        if not self.catalog.installed(voice):
            self._download_voice(voice)
        else:
            self.speak()

    def _download_voice(self, voice):
        speak_after_download = bool(self.text_view.get_buffer().get_char_count())
        self._busy = self._downloading = True
        self.speak_button.set_sensitive(False)
        self.progress_bar.set_fraction(0)
        self.progress_bar.set_opacity(1)
        self._status("Downloading voice…")

        def progress(received, total):
            def update():
                self.progress_bar.set_fraction(received / total if total else 0)
                return False
            GLib.idle_add(update)

        def work():
            return self.catalog.download(voice, progress=progress)

        def done(_path):
            self._downloading = self._busy = False
            self.progress_bar.set_opacity(0)
            self._render_voices()
            self._status("")
            if speak_after_download:
                self.speak()
            return False

        def failed(error):
            self._downloading = self._busy = False
            self.progress_bar.set_opacity(0)
            self.speak_button.set_sensitive(True)
            self._status(f"Download failed: {error}")
            return False

        self._thread(work, done, failed)

    def speak(self):
        buffer = self.text_view.get_buffer()
        text = buffer.get_text(buffer.get_start_iter(), buffer.get_end_iter(), False).strip()
        if not text or self._busy:
            return
        index = self.voice_dropdown.get_selected()
        if index >= len(self.voices):
            return
        voice = self.voices[index]
        if not self.catalog.installed(voice):
            self._download_voice(voice)
            return
        self._busy = True
        self.speak_button.set_sensitive(False)
        self._status("Speaking…")
        buffer.set_text("")
        engine = ENGINES["piper"]()
        model_path = self.catalog.model_path(voice)
        hear_default = self.hear_switch.get_active()
        extra_devices = self.settings.get("additional-devices")

        def work():
            import os
            wav_path = engine.synthesize(text, model_path)
            try:
                sink = self.sink_name or self.audio.ensure_sink()
                self.audio.play(wav_path, [sink, *extra_devices], hear_default)
            finally:
                try:
                    os.unlink(wav_path)
                except FileNotFoundError:
                    pass

        def done(_value):
            self._busy = False
            self.speak_button.set_sensitive(True)
            self._status("")
            return False

        def failed(error):
            self._busy = False
            self.speak_button.set_sensitive(True)
            self._status(f"Speech failed: {error}")
            return False

        self._thread(work, done, failed)
