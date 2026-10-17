# Speech engines implement a small common interface for future backends.

import subprocess
import sys
import tempfile
from abc import ABC, abstractmethod


class SpeechEngine(ABC):
    engine_id = ""
    display_name = ""

    @abstractmethod
    def synthesize(self, text, model_path):
        raise NotImplementedError


class PiperEngine(SpeechEngine):
    engine_id = "piper"
    display_name = "Piper"

    def synthesize(self, text, model_path):
        temporary = tempfile.NamedTemporaryFile(prefix="hovir-", suffix=".wav", delete=False)
        temporary.close()
        try:
            result = subprocess.run(
                [sys.executable, "-m", "piper", "-m", model_path, "-f", temporary.name],
                input=text,
                text=True,
                capture_output=True,
                timeout=300,
            )
            if result.returncode:
                raise RuntimeError(result.stderr.strip() or "Piper could not synthesize speech")
            return temporary.name
        except Exception:
            import os
            try:
                os.unlink(temporary.name)
            except FileNotFoundError:
                pass
            raise


ENGINES = {"piper": PiperEngine}
