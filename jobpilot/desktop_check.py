"""Opt-in native dashboard diagnostics, shared by source and frozen launchers."""

from __future__ import annotations

import json
import os
import sys
import tempfile
import threading
import time
from pathlib import Path


def verify_dashboard(*, url, report_path, show_dashboard, instance_factory, timeout=45) -> dict:
    result = {
        "ok": False,
        "loaded": False,
        "quit": False,
        "native_window": False,
        "menu_dispatched": False,
        "frozen": bool(getattr(sys, "frozen", False)),
        "executable": sys.executable,
    }
    if sys.platform != "darwin":
        result["error"] = "The Cocoa smoke test requires native macOS and a WindowServer"
        return result

    if timeout <= 0:
        raise ValueError("Dashboard verification timeout must be positive")
    import webview
    from PyObjCTools import AppHelper

    original_create = webview.create_window
    old_data = os.environ.get("JOBPILOT_DATA_DIR")
    finished = threading.Event()
    windows = []

    def fail(error):
        result.setdefault("error", str(error))
        # Keep the reason even if a broken native event loop needs the caller's
        # subprocess timeout to end it after our close request.
        report_path.write_text(json.dumps({**result, "ok": False}, indent=2), encoding="utf-8")
        if windows:
            windows[0].destroy()

    def find_menu_item(menu, title):
        for item in menu.itemArray():
            if item.title() == title:
                return item
            if item.hasSubmenu():
                found = find_menu_item(item.submenu(), title)
                if found is not None:
                    return found
        return None

    def quit_through_native_menu():
        try:
            from webview.platforms.cocoa import BrowserView

            result["main_thread"] = threading.current_thread() is threading.main_thread()
            native = BrowserView.instances.get(windows[0].uid)
            result["native_window"] = bool(native and native.window.isVisible())
            item = find_menu_item(BrowserView.app.mainMenu(), "Quit dashboard")
            if item is None or not item.isEnabled():
                raise RuntimeError("The native Quit dashboard menu item is unavailable")
            result["menu_dispatched"] = bool(
                BrowserView.app.sendAction_to_from_(item.action(), item.target(), item)
            )
            if not result["menu_dispatched"]:
                raise RuntimeError("Cocoa did not dispatch the native Quit dashboard action")
        except Exception as error:
            fail(error)

    def loaded():
        try:
            window = windows[0]
            deadline = time.monotonic() + timeout
            while not finished.is_set() and time.monotonic() < deadline:
                document = window.evaluate_js(
                    """({title: document.title, location: location.href,
                    dashboard: !!document.querySelector('#navigation [data-view="settings"]'),
                    connected: document.querySelector('#connectionLabel')?.textContent
                        === 'Local service connected'})"""
                )
                result["document"] = document
                if document and document["dashboard"] and document["connected"]:
                    if not document["title"].startswith("JobPilot"):
                        raise RuntimeError("The loaded document is not the JobPilot dashboard")
                    result["loaded"] = True
                    AppHelper.callAfter(quit_through_native_menu)
                    return
                finished.wait(0.1)
            raise RuntimeError("The native dashboard did not connect to its local service")
        except Exception as error:
            fail(error)

    def create_window(*args, **kwargs):
        # Only this opt-in check redirects the normal window to its caller's
        # disposable service. The current launcher callback stays in use.
        arguments = list(args)
        if len(arguments) > 1:
            arguments[1] = url
        else:
            kwargs["url"] = url
        window = original_create(*arguments, **kwargs)
        windows.append(window)
        window.events.loaded += loaded
        return window

    def timed_out():
        if not finished.is_set():
            fail(f"The Cocoa smoke test exceeded {timeout:g} seconds")

    timer = threading.Timer(timeout, timed_out)
    timer.daemon = True
    try:
        with tempfile.TemporaryDirectory(prefix="jobpilot-cocoa-smoke-") as temporary:
            data = Path(temporary)
            os.environ["JOBPILOT_DATA_DIR"] = str(data)
            instance = instance_factory("JobPilotSmoke", data=data)
            webview.create_window = create_window
            timer.start()
            try:
                show_dashboard(False, data, instance)
                result["quit"] = bool(
                    result["menu_dispatched"] and windows and windows[0].events.closed.is_set()
                )
            finally:
                finished.set()
                instance.close()
    except Exception as error:
        result.setdefault("error", str(error))
    finally:
        finished.set()
        timer.cancel()
        webview.create_window = original_create
        if old_data is None:
            os.environ.pop("JOBPILOT_DATA_DIR", None)
        else:
            os.environ["JOBPILOT_DATA_DIR"] = old_data
    result["ok"] = (
        all(
            result.get(key)
            for key in ("loaded", "quit", "native_window", "main_thread", "menu_dispatched")
        )
        and "error" not in result
    )
    return result
