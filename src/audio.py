# PulseAudio protocol control and GStreamer playback (works with PipeWire-Pulse).

import threading
import re

import gi
gi.require_version("Gst", "1.0")
from gi.repository import Gst
from pulsectl import Pulse


class AudioError(RuntimeError):
    pass


class AudioRouter:
    # Keep the existing internal name so communication apps can reconnect to
    # the corrected sink after the one-time description migration.
    BASE_NAME = "hovir_tts"
    MARKER = "hovir.created=true"

    def __init__(self):
        Gst.init(None)

    def _pulse(self):
        try:
            return Pulse("hovir-audio")
        except Exception as error:
            raise AudioError(f"Could not connect to the audio server: {error}") from error

    def ensure_sink(self):
        with self._pulse() as pulse:
            modules = pulse.module_list()
            for module in modules:
                argument = module.argument or ""
                sink_name = self._module_sink_name(argument)
                if module.name == "module-null-sink" and self._is_our_name(sink_name):
                    if self.MARKER in argument and ",device.icon_name=" in argument:
                        # The previous comma-separated proplist made the whole
                        # string appear as the device description.
                        pulse.module_unload(module.index)
                        continue
                    return sink_name

            existing = {sink.name for sink in pulse.sink_list()}
            suffix = 1
            name = self.BASE_NAME
            while name in existing:
                suffix += 1
                name = f"{self.BASE_NAME}_{suffix}"
            args = f'sink_name={name} sink_properties=device.description="Hovir Virtual Audio Sink"'
            try:
                pulse.module_load("module-null-sink", args)
            except Exception as error:
                raise AudioError(f"Could not create the Hovir virtual microphone: {error}") from error
            return name

    def devices(self):
        with self._pulse() as pulse:
            return [(sink.name, sink.description or sink.name) for sink in pulse.sink_list()]

    def remove_hovir_sinks(self):
        removed = 0
        with self._pulse() as pulse:
            for module in pulse.module_list():
                argument = module.argument or ""
                sink_name = self._module_sink_name(argument)
                if (module.name == "module-null-sink"
                        and (self._is_our_name(sink_name)
                             or (sink_name == self.BASE_NAME and self.MARKER in argument))):
                    pulse.module_unload(module.index)
                    removed += 1
        return removed

    @classmethod
    def _is_our_name(cls, name):
        return bool(name and re.fullmatch(re.escape(cls.BASE_NAME) + r"(?:_(?:[2-9]|[1-9][0-9]+))?", name))

    @staticmethod
    def _module_sink_name(argument):
        for token in argument.split():
            if token.startswith("sink_name="):
                return token.split("=", 1)[1].strip("\"'")
        return None

    @staticmethod
    def _play_one(wav_path, device):
        pipeline = Gst.ElementFactory.make("playbin", "hovir-playback")
        sink = Gst.ElementFactory.make("pulsesink", "hovir-pulse-output")
        if pipeline is None or sink is None:
            raise AudioError("GStreamer PulseAudio output is unavailable in this runtime")
        if device:
            sink.set_property("device", device)
        pipeline.set_property("audio-sink", sink)
        pipeline.set_property("uri", "file://" + wav_path)
        state_change = pipeline.set_state(Gst.State.PLAYING)
        if state_change == Gst.StateChangeReturn.FAILURE:
            pipeline.set_state(Gst.State.NULL)
            raise AudioError("GStreamer could not start audio playback")
        try:
            bus = pipeline.get_bus()
            message = bus.timed_pop_filtered(
                Gst.CLOCK_TIME_NONE,
                Gst.MessageType.EOS | Gst.MessageType.ERROR,
            )
            if message and message.type == Gst.MessageType.ERROR:
                error, _debug = message.parse_error()
                raise AudioError(str(error))
        finally:
            pipeline.set_state(Gst.State.NULL)

    def play(self, wav_path, sink_names, hear_default):
        targets = list(dict.fromkeys(sink_names))
        if hear_default:
            with self._pulse() as pulse:
                default_sink = pulse.server_info().default_sink_name
            if default_sink not in targets:
                targets.append(None)
        if not targets:
            return
        errors = []

        def play(device):
            try:
                self._play_one(wav_path, device)
            except Exception as error:
                errors.append(str(error))

        threads = [threading.Thread(target=play, args=(target,)) for target in targets]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join()
        if errors:
            raise AudioError("; ".join(errors))
