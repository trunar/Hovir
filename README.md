# Hovir

Hovir is a GTK 4/libadwaita desktop text-to-speech app. Piper voices are listed from the public [`rhasspy/piper-voices`](https://huggingface.co/rhasspy/piper-voices) Hugging Face repository and downloaded when selected. Voice models are stored in Hovir's Flatpak data directory (`~/.var/app/io.github.trunar.Hovir/data/voices/`); only catalog metadata is cached. Use **Manage Downloaded Voices** in the main menu to remove voices individually or clear all downloaded voices.

## Build and run

Install GNOME Builder's GNOME 50 SDK/runtime and Flatpak Builder, then from this checkout run:

```sh
flatpak-builder --user --install --force-clean .flatpak/build-dir io.github.trunar.Hovir.json
flatpak run io.github.trunar.Hovir
```

The Flatpak build installs the pinned Piper and PulseAudio protocol Python dependencies from PyPI. It needs network access during the dependency build step and at runtime for catalog refreshes and voice downloads. The catalog can use cached metadata while offline, and downloaded voices remain usable.

Enter speaks the text. Shift+Enter inserts a newline. The Speak button tooltip shows the shortcut.

## Audio

Hovir creates a persistent virtual output named `hovir_tts` (shown as “Hovir Virtual Audio Sink”) through the PulseAudio protocol server provided by PipeWire on most GNOME systems. Communication apps should select its monitor source as their microphone. Speech always plays to this sink. **Hear myself** also plays it through the default output, and **Additional output** can send it to one other selected device. Hovir avoids duplicating playback when that device is already the default output.

The sink stays loaded after Hovir exits so other apps can keep their selected microphone. Remove it from Hovir's main menu before uninstalling. Uninstalling the Flatpak cannot unload a module already held by the audio server; if Hovir has already been removed, the sink disappears when the audio server/session restarts. If your audio server supports `pactl`, you can also locate and unload the `module-null-sink` whose arguments contain `hovir.created=true`.
