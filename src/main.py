# main.py
#
# Copyright 2026 Andrii Indyk
#
# This program is free software: you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation, either version 3 of the License, or
# (at your option) any later version.
#
# This program is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU General Public License for more details.
#
# You should have received a copy of the GNU General Public License
# along with this program.  If not, see <https://www.gnu.org/licenses/>.
#
# SPDX-License-Identifier: GPL-3.0-or-later

import platform
import sys
import gi

from gettext import gettext as _

gi.require_version('Gtk', '4.0')
gi.require_version('Adw', '1')

from gi.repository import Gtk, Gio, Adw, GLib
from .window import HovirWindow


class HovirApplication(Adw.Application):
    """The main application singleton class."""

    def __init__(self, version):
        super().__init__(application_id='io.github.trunar.Hovir',
                         flags=Gio.ApplicationFlags.DEFAULT_FLAGS,
                         resource_base_path='/io/github/trunar/Hovir')
        self.version = version
        self.create_action('quit', lambda *_: self.quit(), ['<control>q'])
        self.create_action('about', self.on_about_action)
        self.create_action('shortcuts', self.on_shortcuts_action, ['<control>question'])
        self.create_action('remove-audio-sink', self.on_remove_audio_sink_action)
        self.create_action('manage-voices', self.on_manage_voices_action)

    def do_activate(self):
        """Called when the application is activated.

        We raise the application's main window, creating it if
        necessary.
        """
        win = self.props.active_window
        if not win:
            win = HovirWindow(application=self)
        win.present()

    def on_about_action(self, *args):
        """Callback for the app.about action."""
        os_name = GLib.get_os_info('PRETTY_NAME') or platform.platform()
        about = Adw.AboutDialog(application_name='Hovir',
                                application_icon='io.github.trunar.Hovir',
                                developer_name='Andrii Indyk',
                                version=self.version,
                                developers=['Andrii Indyk'],
                                copyright='© 2026 Andrii Indyk',
                                website='https://github.com/trunar/Hovir',
                                issue_url='https://github.com/trunar/Hovir/issues',
                                license_type=Gtk.License.CUSTOM,
                                license=(
                                    'This application is licensed under the GNU General Public '
                                    'License, version 3 or later. See COPYING for details.\n\n'
                                    'This application comes with absolutely no warranty.'
                                ),
                                debug_info=(
                                    f'Hovir {self.version}\n'
                                    f'Operating system: {os_name}\n'
                                    f'Architecture: {platform.machine()}\n'
                                    f'Python: {platform.python_version()}\n'
                                    f'GTK: {Gtk.get_major_version()}.{Gtk.get_minor_version()}'
                                ),
                                debug_info_filename='hovir-debug-info.txt')
        about.add_legal_section(
            _('Piper speech engine'),
            '© Open Home Foundation',
            Gtk.License.GPL_3_0,
            'Piper is distributed under GPL-3.0-or-later.',
        )
        about.add_legal_section(
            _('Piper voice catalog'),
            None,
            Gtk.License.MIT_X11,
            'The rhasspy/piper-voices repository is licensed under the MIT License.',
        )
        about.add_link(_('Piper project'), 'https://github.com/OHF-Voice/piper1-gpl')
        about.add_link(
            _('Piper voice catalog'),
            'https://huggingface.co/rhasspy/piper-voices',
        )
        about.present(self.props.active_window)

    def on_shortcuts_action(self, *_args):
        builder = Gtk.Builder.new_from_resource('/io/github/trunar/Hovir/shortcuts-dialog.ui')
        dialog = builder.get_object('shortcuts_dialog')
        dialog.present(self.props.active_window)

    def on_remove_audio_sink_action(self, *_args):
        window = self.props.active_window
        if window:
            window.request_remove_sink()

    def on_manage_voices_action(self, *_args):
        window = self.props.active_window
        if window:
            window.open_voice_manager()

    def create_action(self, name, callback, shortcuts=None):
        """Add an application action.

        Args:
            name: the name of the action
            callback: the function to be called when the action is
              activated
            shortcuts: an optional list of accelerators
        """
        action = Gio.SimpleAction.new(name, None)
        action.connect("activate", callback)
        self.add_action(action)
        if shortcuts:
            self.set_accels_for_action(f"app.{name}", shortcuts)


def main(version):
    """The application's entry point."""
    app = HovirApplication(version)
    return app.run(sys.argv)
