# Licensed to the Apache Software Foundation (ASF) under one
# or more contributor license agreements.  See the NOTICE file
# distributed with this work for additional information
# regarding copyright ownership.  The ASF licenses this file
# to you under the Apache License, Version 2.0 (the
# "License"); you may not use this file except in compliance
# with the License.  You may obtain a copy of the License at
#
#   http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing,
# software distributed under the License is distributed on an
# "AS IS" BASIS, WITHOUT WARRANTIES OR CONDITIONS OF ANY
# KIND, either express or implied.  See the License for the
# specific language governing permissions and limitations
# under the License.
#

"""Request-independent refresh of a short-lived provisioning credential."""
import base64
import binascii
import secrets
import threading
import time

from .kube_client import ProvisioningError, ProvisioningKubeClient


def decode_provisioning_token(secret):
    try:
        if not isinstance(secret, dict) or secret.get("type") != "Opaque":
            raise ValueError()
        token = base64.b64decode(secret["data"]["token"], validate=True)
        if not token.strip() or len(token) > 8192:
            raise ValueError()
        return token
    except (KeyError, TypeError, ValueError, binascii.Error):
        raise ProvisioningError("User provisioning authorization is not configured", 503) from None


def _load_secret():
    return ProvisioningKubeClient().provisioning_secret()


class ProvisioningAuthorizer:
    REFRESH_SECONDS = 1.0
    MAX_AGE_SECONDS = 2.0

    def __init__(self, loader=_load_secret, clock=time.monotonic):
        self._loader = loader
        self._clock = clock
        self._lock = threading.Lock()
        self._snapshot = None
        self._thread = None
        self._stop = threading.Event()

    def start(self):
        # Starting is lazy so importing the app and using unrelated routes do
        # not require Kubernetes or the optional provisioning Secret.
        with self._lock:
            if self._thread is None and not self._stop.is_set():
                worker = threading.Thread(target=self._run, name="provisioning-credential", daemon=True)
                worker.start()
                self._thread = worker

    def close(self):
        self._stop.set()
        with self._lock:
            self._snapshot = None

    def _refresh_once(self):
        # Age starts before I/O: a delayed response must not extend the lifetime
        # of credentials read before rotation or revocation.
        started = self._clock()
        try:
            token = decode_provisioning_token(self._loader())
            expires = started + self.MAX_AGE_SECONDS
            snapshot = (token, expires) if self._clock() < expires else None
        except Exception:
            # Dependency/configuration failures revoke the local snapshot.
            # Do not retain exception bodies, backend URLs, or credential data.
            snapshot = None
        with self._lock:
            self._snapshot = None if self._stop.is_set() else snapshot

    def _run(self):
        while not self._stop.is_set():
            self._refresh_once()
            if self._stop.wait(self.REFRESH_SECONDS):
                return

    def authorize(self, supplied):
        self.start()
        with self._lock:
            snapshot = self._snapshot
        if snapshot is None or self._clock() >= snapshot[1]:
            raise ProvisioningError("Provisioning authorization temporarily unavailable", 503)
        if not secrets.compare_digest(supplied, snapshot[0]):
            raise ProvisioningError("Missing or invalid provisioning token", 401)


provisioning_authorizer = ProvisioningAuthorizer()
