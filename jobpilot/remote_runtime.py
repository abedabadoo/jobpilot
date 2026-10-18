"""Lifecycle for a separate, paired-device-only loopback web server."""

import threading
import time

from .interventions import InterventionBroker
from .remote_gateway import RemoteGateway


class RemoteRuntime:
    def __init__(self, data_dir, stop_event, vapid_subject="mailto:jobpilot@localhost.localdomain"):
        self.data_dir = data_dir
        self.vapid_subject = vapid_subject
        self.broker = InterventionBroker(data_dir, stop_event, on_change=self._notify)
        self.auth = None
        self.notifications = None
        self.gateway = RemoteGateway(data_dir)
        self.server = None
        self.thread = None
        self.starting = False
        self.error = ""
        self.lock = threading.RLock()
        self._lifecycle = threading.RLock()
        self._generation = 0
        self._stop_count = 0
        self._stop_complete = threading.Event()
        self._stop_complete.set()

    def _listening(self):
        # Uvicorn's started flag is historical, not a liveness indicator.
        return bool(
            self.server
            and self.server.started
            and not self.server.should_exit
            and self.thread
            and self.thread.is_alive()
        )

    def _allowed(self, generation):
        # This predicate is also called under the gateway lock. Do not acquire
        # the runtime lock here: lifecycle/status take locks in the other order.
        return generation == self._generation and self._stop_count == 0

    def _notify(self, case):
        if self.notifications:
            self.notifications.notify(case)

    def status(self):
        with self.lock:
            result = {
                "starting": self.starting,
                "listening": self._listening(),
                "error": self.error,
            }
            notifications = self.notifications
        result.update(
            gateway=self.gateway.status(),
            waiting=sum(case["state"] == "waiting" for case in self.broker.list_cases()),
            notifications=notifications.status() if notifications else {"subscribed_devices": 0},
        )
        return result

    def start_async(self):
        with self.lock:
            if self.starting:
                return
            self._generation += 1
            generation = self._generation
            self.starting = True
        threading.Thread(
            target=self._start, args=(generation,), name="remote-start", daemon=True
        ).start()

    def _start(self, generation):
        try:
            # An enable request arriving during disable belongs to a newer
            # generation, but must wait until the old server releases the port.
            self._stop_complete.wait()
            with self._lifecycle:
                if not self._allowed(generation):
                    return
                with self.lock:
                    if not self._listening():
                        if self.thread and self.thread.is_alive():
                            raise RuntimeError("Previous companion is still stopping")
                        import uvicorn

                        from .remote import create_remote_app
                        from .remote_auth import RemoteAuth
                        from .remote_notifications import RemoteNotifications

                        self.auth = RemoteAuth(self.data_dir)
                        self.notifications = RemoteNotifications(
                            self.data_dir,
                            session_active=self.auth.valid_hash,
                            vapid_subject=self.vapid_subject,
                        )
                        companion = create_remote_app(self.broker, self.auth, self.notifications)
                        server = uvicorn.Server(
                            uvicorn.Config(
                                companion,
                                host="127.0.0.1",
                                port=8766,
                                log_level="error",
                                access_log=False,
                                proxy_headers=True,
                                forwarded_allow_ips="127.0.0.1",
                            )
                        )
                        thread = threading.Thread(
                            target=self._serve, args=(server,), name="remote-portal", daemon=True
                        )
                        self.server, self.thread = server, thread
                        # Publish the thread and start it under the same lock;
                        # stop() must never join a not-yet-started Thread.
                        thread.start()
                    else:
                        server, thread = self.server, self.thread
                deadline = time.monotonic() + 8
                while (
                    not server.started
                    and thread.is_alive()
                    and time.monotonic() < deadline
                    and self._allowed(generation)
                ):
                    time.sleep(0.05)
                if not self._allowed(generation):
                    server.should_exit = True
                    thread.join(timeout=3)
                    return
                if not self._listening():
                    server.should_exit = True
                    thread.join(timeout=3)
                    raise RuntimeError("Companion portal did not start on loopback port 8766")
                self.gateway.start(allowed=lambda: self._allowed(generation))
                if not self._allowed(generation):
                    self.gateway.stop()
                    server.should_exit = True
                    thread.join(timeout=3)
                    return
                with self.lock:
                    self.error = ""
        except Exception:
            with self.lock:
                if generation == self._generation:
                    self.error = "Remote access could not start. Check the local runtime, credential vault and HTTPS tunnel."
        finally:
            with self.lock:
                if generation == self._generation:
                    self.starting = False

    def _serve(self, server):
        try:
            server.run()
        except (Exception, SystemExit):
            with self.lock:
                if self.server is server:
                    self.error = "Companion port 8766 is unavailable."
        finally:
            # A tunnel must never outlive its companion: another local process
            # could otherwise bind the released port and become publicly served.
            with self.lock:
                unexpected = self.server is server and not server.should_exit
                if unexpected:
                    # Cancel a start that passed readiness but has not yet
                    # launched its gateway. Stopping only the current tunnel
                    # would still allow that later spawn to expose a dead port.
                    self._generation += 1
                    self.starting = False
                    server.should_exit = True
                    self.error = "Companion portal stopped. Reconnect from local remote setup."
            if unexpected:
                self.gateway.stop()

    def pairing_link(self):
        url = self.gateway.status()["url"]
        return url + "/#pair=" + self.auth.pairing_secret() if url and self.auth else ""

    def stop(self):
        with self.lock:
            self._generation += 1
            generation = self._generation
            self.starting = False
            self._stop_count += 1
            self._stop_complete.clear()
            server, thread = self.server, self.thread
            if server:
                server.should_exit = True
        try:
            # Wake a start currently awaiting its tunnel before waiting for
            # lifecycle ownership. Its generation is already invalidated.
            self.gateway.stop()
            with self._lifecycle:
                if thread and thread.is_alive():
                    thread.join(timeout=3)
        finally:
            with self.lock:
                self._stop_count -= 1
                if not self._stop_count:
                    self._stop_complete.set()
                if generation == self._generation:
                    self.starting = False
