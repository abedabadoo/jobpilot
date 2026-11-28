"""Start only the explicitly installed, fixed loopback model on demand."""
from __future__ import annotations
import atexit
import json
import os
from pathlib import Path
import platform
import subprocess
import threading
import time
import urllib.error
import urllib.request

from .models import ModelSettings

HOME_DIR=Path.home()/"Library/Application Support/ResumeForge"
MODEL="resumeforge-qwen35-4b"
URL="http://127.0.0.1:18766"
BINARY=HOME_DIR/"inference/b12189/llama-b12189/llama-server"
WEIGHTS=HOME_DIR/"models/Qwen3.5-4B-Q4_K_M.gguf"
_lock=threading.Lock()
_child=None


def installed():
    return platform.system()=="Darwin" and BINARY.is_file() and WEIGHTS.is_file() and WEIGHTS.stat().st_size==2740937888 and (HOME_DIR/"laptop-model.json").is_file()


def default_settings():
    if installed():
        return ModelSettings(strategy="laptop",provider="openai-compatible",base_url=URL+"/v1",model=MODEL,api_key_env="",timeout_seconds=300,max_rounds=3)
    return ModelSettings()


def _ready():
    try:
        with urllib.request.urlopen(URL+"/v1/models",timeout=2) as r:
            models=json.load(r).get("data",[])
        if not any(m.get("id")==MODEL for m in models):
            raise RuntimeError("Port 18766 is in use by a different model service; no resume was sent.")
        return True
    except urllib.error.HTTPError as e:
        if e.code==503:return None
        raise RuntimeError("An incompatible service is listening on the laptop model port.") from e
    except (urllib.error.URLError,TimeoutError):
        return False


def ensure_running(settings):
    global _child
    if not (settings.provider=="openai-compatible" and settings.model==MODEL and settings.base_url.rstrip("/")==URL+"/v1" and installed()):
        return
    with _lock:
        if _child and _child.poll() is None:return
        state = _ready()
        if state:return
        if state is None:
            for _ in range(100):
                time.sleep(.35)
                if _ready():return
            raise RuntimeError('An existing model service did not finish loading; no second copy was started.')
        log=HOME_DIR/"inference/server.log"
        args=[str(BINARY),"--offline","-m",str(WEIGHTS),"-a",MODEL,"--host","127.0.0.1","--port","18766",
              "-ngl","0","-c","8192","-np","1","-t","4","-tb","4","-b","192","-ub","96","--reasoning","off",
              "--no-webui","--no-slots","--cors-origins","http://127.0.0.1:8766","--no-cors-credentials","--sleep-idle-seconds","300"]
        with log.open("w") as stream:
            _child=subprocess.Popen(args,stdin=subprocess.DEVNULL,stdout=stream,stderr=subprocess.STDOUT,start_new_session=True)
        for _ in range(100):
            if _child.poll() is not None:raise RuntimeError("Local model failed to start. See "+str(log))
            if _ready():return
            time.sleep(.35)
        _stop()
        raise RuntimeError("Timed out starting the local Qwen model.")


@atexit.register
def _stop():
    if _child and _child.poll() is None:
        _child.terminate()
