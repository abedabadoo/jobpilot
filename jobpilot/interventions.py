"""Bounded remote input executed exclusively by the browser's owning thread."""

import json
import math
import re
import secrets
import threading
import time
from collections import deque
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urlsplit, urlunsplit

KEYS = {
    "Tab",
    "Shift+Tab",
    "Enter",
    "Backspace",
    "Delete",
    "Escape",
    "ArrowLeft",
    "ArrowRight",
    "ArrowUp",
    "ArrowDown",
    "Home",
    "End",
    "Space",
    "Control+A",
}


def _now():
    return datetime.now(timezone.utc).isoformat()


def _safe_url(url):
    parts = urlsplit(url)
    if parts.scheme not in ("http", "https"):
        return ""
    return urlunsplit((parts.scheme, parts.hostname or "", parts.path, "", ""))


class InterventionBroker:
    def __init__(self, data_dir, stop_event=None, on_change=None):
        self.path = Path(data_dir) / "remote-interventions.json"
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.stop_event = stop_event or threading.Event()
        self.on_change = on_change
        self.lock = threading.RLock()
        self.changed = threading.Event()
        self.frames = {}
        self.queues = {}
        try:
            records = json.loads(self.path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            records = []
        self.cases = {
            item["id"]: item for item in records if isinstance(item, dict) and item.get("id")
        }
        for case in self.cases.values():
            if case.get("state") == "waiting":
                case.update(
                    state="interrupted",
                    updated_at=_now(),
                    last_error="Worker restarted. Review the application before reopening it.",
                )
        if self.cases:
            self._save()

    def _save(self):
        records = list(self.cases.values())[-100:]
        temporary = self.path.with_suffix(".tmp")
        temporary.write_text(json.dumps(records, ensure_ascii=False), encoding="utf-8")
        temporary.replace(self.path)

    def list_cases(self):
        with self.lock:
            return [dict(case) for case in reversed(list(self.cases.values()))]

    def get_case(self, case_id):
        with self.lock:
            return dict(self.cases[case_id])

    def frame(self, case_id):
        with self.lock:
            case = self.cases[case_id]
            if case["state"] != "waiting" or case_id not in self.frames:
                raise ValueError("Browser view is unavailable.")
            return dict(self.frames[case_id])

    def command(self, case_id, body):
        with self.lock:
            case = self.cases[case_id]
            if case["state"] != "waiting":
                raise ValueError("This intervention has ended.")
            if (
                not isinstance(body, dict)
                or not isinstance(body.get("kind"), str)
                or body["kind"]
                not in {"click", "scroll", "key", "text", "code", "resume", "cancel"}
            ):
                raise ValueError("Unsupported browser input.")
            kind = body["kind"]
            if kind != "cancel" and (
                not case.get("view_id") or body.get("view_id") != case["view_id"]
            ):
                raise ValueError("Browser view changed. Refresh the view before interacting.")
            command = {"kind": kind, "view_id": case.get("view_id")}
            if kind == "click":
                for axis, maximum in [("x", case["width"]), ("y", case["height"])]:
                    value = body.get(axis)
                    if (
                        isinstance(value, bool)
                        or not isinstance(value, (int, float))
                        or not math.isfinite(value)
                        or not 0 <= value < maximum
                    ):
                        raise ValueError("Click is outside the browser view.")
                    command[axis] = value
            elif kind == "scroll":
                value = body.get("delta_y")
                if (
                    isinstance(value, bool)
                    or not isinstance(value, (int, float))
                    or not math.isfinite(value)
                    or abs(value) > 2000
                ):
                    raise ValueError("Scroll exceeds the allowed distance.")
                command["delta_y"] = value
            elif kind == "key":
                if not isinstance(body.get("key"), str) or body["key"] not in KEYS:
                    raise ValueError("Unsupported key.")
                command["key"] = body["key"]
            elif kind in ("text", "code"):
                value = body.get(kind)
                if not isinstance(value, str) or not 1 <= len(value) <= (
                    32 if kind == "code" else 4096
                ):
                    raise ValueError("Input has an invalid length.")
                if kind == "code" and not re.fullmatch(r"[\w -]+", value, flags=re.ASCII):
                    raise ValueError("Code contains unsupported characters.")
                command[kind] = value
            queue = self.queues.get(case_id)
            if queue is None or len(queue) >= 32:
                raise ValueError("Input queue is full. Wait for the browser to respond.")
            queue.append(command)
            self.changed.set()
            return {"ok": True, "queued": True}

    def _observe(self, page, case_id, identity):
        observation = page.evaluate(
            "() => ({url:location.href,width:innerWidth,height:innerHeight,epoch:performance.timeOrigin})"
        )
        epoch = (
            id(page),
            observation["url"],
            observation["width"],
            observation["height"],
            observation["epoch"],
        )
        png = page.screenshot(full_page=False, timeout=2500)
        with self.lock:
            case = self.cases[case_id]
            if epoch != identity:
                case["view_id"] = secrets.token_urlsafe(16)
            case.update(
                width=observation["width"],
                height=observation["height"],
                url=_safe_url(observation["url"]),
            )
            self.frames[case_id] = {
                "png": png,
                **{key: case[key] for key in ("view_id", "width", "height", "url")},
            }
        return epoch

    @staticmethod
    def _enter_code(page, value):
        candidates = []
        for frame in page.frames:
            for field in frame.locator("input").all():
                if not field.is_visible() or not field.is_enabled():
                    continue
                info = field.evaluate(
                    '(e) => ({type:e.type,autocomplete:e.autocomplete,label:[e.id,e.name,e.placeholder,e.getAttribute("aria-label"),...Array.from(e.labels||[],x=>x.innerText)].join(" ")})'
                )
                if info["type"] in ("password", "email", "hidden"):
                    continue
                if info["autocomplete"] == "one-time-code" or re.search(
                    r"\b(code|otp|verification|passcode)\b", info["label"], re.I
                ):
                    if not re.search(
                        r"\b(zip|postal|cvv|security code|card|coupon)\b", info["label"], re.I
                    ):
                        candidates.append(field)
        if len(candidates) != 1:
            raise ValueError("Select the code field in the browser view and use Type text.")
        candidates[0].fill(value, timeout=3000)

    def pause(
        self,
        page,
        job,
        *,
        kind,
        note,
        submitted=False,
        ready=None,
        auto_resume=False,
        timeout_seconds=28800,
    ):
        case_id = secrets.token_urlsafe(18)
        seconds = max(0.05, min(float(timeout_seconds), 86400))
        created = _now()
        case = {
            "id": case_id,
            "job_id": job.get("id"),
            "title": str(job.get("title", ""))[:200],
            "company": str(job.get("company", ""))[:200],
            "kind": kind,
            "note": note,
            "submitted": bool(submitted),
            "state": "waiting",
            "created_at": created,
            "updated_at": created,
            "expires_at": datetime.fromtimestamp(time.time() + seconds, timezone.utc).isoformat(),
            "url": "",
            "last_error": "",
            "view_id": "",
            "width": 0,
            "height": 0,
        }
        with self.lock:
            self.cases[case_id] = case
            self.queues[case_id] = deque()
            self._save()
        outcome = "interrupted"
        identity = None
        next_frame = 0
        next_ready = 0
        deadline = time.monotonic() + seconds
        notified = False
        try:
            while True:
                if self.stop_event.is_set():
                    break
                if time.monotonic() >= deadline:
                    outcome = "expired"
                    break
                pages = [item for item in page.context.pages if not item.is_closed()]
                if page.is_closed() and not pages:
                    outcome = "closed"
                    break
                active = pages[-1] if pages else page
                if time.monotonic() >= next_frame:
                    try:
                        identity = self._observe(active, case_id, identity)
                    except Exception:
                        with self.lock:
                            case["last_error"] = "Browser is loading. Refresh the view shortly."
                    next_frame = time.monotonic() + 0.65
                if not notified and case.get("view_id"):
                    notified = True
                    if self.on_change:
                        threading.Thread(
                            target=self._notify, args=(dict(case),), daemon=True
                        ).start()
                with self.lock:
                    command = self.queues[case_id].popleft() if self.queues[case_id] else None
                if command:
                    action = command["kind"]
                    if action == "cancel":
                        outcome = "cancelled"
                        break
                    # Re-observe before input; navigation may occur between screenshots.
                    current = active.evaluate(
                        "() => [location.href,innerWidth,innerHeight,performance.timeOrigin]"
                    )
                    if (id(active), *current) != identity or command["view_id"] != case["view_id"]:
                        with self.lock:
                            case["last_error"] = "Browser view changed. Refresh before interacting."
                        next_frame = 0
                        continue
                    try:
                        if action == "resume":
                            if ready is None or ready():
                                outcome = "resume"
                                break
                            raise ValueError(
                                "The sign-in or verification step is still waiting. Complete it in the browser view first."
                            )
                        if not submitted and ready and ready():
                            raise ValueError(
                                "Sign-in is complete. Resume the worker before continuing the application."
                            )
                        if action == "click":
                            active.mouse.click(command["x"], command["y"])
                        elif action == "scroll":
                            active.mouse.wheel(0, command["delta_y"])
                        elif action == "key":
                            active.keyboard.press(command["key"])
                        elif action == "text":
                            active.keyboard.insert_text(command["text"])
                        elif action == "code":
                            self._enter_code(active, command["code"])
                        with self.lock:
                            case["last_error"] = ""
                        next_frame = 0
                    except ValueError as exc:
                        with self.lock:
                            case["last_error"] = str(exc)
                    except Exception:
                        with self.lock:
                            case["last_error"] = (
                                "Input could not be completed. Refresh the view and try again."
                            )
                    finally:
                        command.clear()
                if auto_resume and ready and time.monotonic() >= next_ready:
                    try:
                        if ready():
                            outcome = "resume"
                            break
                    except Exception:
                        pass
                    next_ready = time.monotonic() + 1
                self.changed.wait(0.08)
                self.changed.clear()
        except Exception:
            outcome = "closed" if page.is_closed() else "interrupted"
        finally:
            with self.lock:
                case.update(
                    state="completed" if outcome == "resume" else outcome, updated_at=_now()
                )
                self.frames.pop(case_id, None)
                self.queues.pop(case_id, None)
                self._save()
        return outcome

    def _notify(self, case):
        try:
            self.on_change(case)
        except Exception:
            pass
