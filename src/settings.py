from gi.repository import Gio


class Settings:
    def __init__(self):
        self._settings = Gio.Settings.new("io.github.trunar.Hovir")

    def get(self, key):
        return self._settings.get_value(key).unpack()

    def set(self, key, value):
        if key in ("hear-myself",):
            self._settings.set_boolean(key, bool(value))
        elif key in ("additional-devices",):
            self._settings.set_strv(key, list(value))
        else:
            self._settings.set_string(key, str(value))

    @property
    def gsettings(self):
        return self._settings
