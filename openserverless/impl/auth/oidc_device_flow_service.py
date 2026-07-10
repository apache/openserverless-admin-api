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
import base64
import hashlib
import os
import secrets
import time

import requests

import openserverless.common.response_builder as res_builder
from openserverless.impl.auth.auth_service import AuthService


_DEVICE_FLOWS = {}


class OidcDeviceFlowService:

    def __init__(
        self,
        environ=os.environ,
        http_client=requests,
        auth_service=None,
        store=None,
        now=None,
    ):
        self._environ = environ
        self._http_client = http_client
        self._auth_service = auth_service if auth_service is not None else AuthService(environ=environ)
        self._store = store if store is not None else _DEVICE_FLOWS
        self._now = now if now is not None else time.time

    def start(self, requested_namespace=None):
        try:
            verifier, challenge = self._create_pkce_pair()
            response = self._http_client.post(
                self._device_authorization_url(),
                data=self._device_authorization_form(challenge),
                headers={"Content-Type": "application/x-www-form-urlencoded"},
                timeout=10,
            )
            payload = response.json()
        except Exception:
            return res_builder.build_error_message("Unable to start SSO login", 502)

        if response.status_code >= 400:
            return res_builder.build_error_message(
                self._provider_error_message(payload, "Unable to start SSO login"),
                502,
            )

        flow_id = secrets.token_urlsafe(32)
        expires_in = int(payload.get("expires_in", 600))
        self._cleanup_expired()
        self._store[flow_id] = {
            "device_code": payload["device_code"],
            "verifier": verifier,
            "expires_at": self._now() + expires_in,
            "interval": int(payload.get("interval", 5)),
            "requested_namespace": requested_namespace,
        }

        return res_builder.build_response_with_data(
            {
                "flow_id": flow_id,
                "user_code": payload.get("user_code"),
                "verification_uri": payload.get("verification_uri"),
                "verification_uri_complete": payload.get("verification_uri_complete"),
                "expires_in": expires_in,
                "interval": int(payload.get("interval", 5)),
            }
        )

    def poll(self, flow_id):
        flow = self._store.get(flow_id)
        if not flow:
            return res_builder.build_error_message("Invalid SSO flow", 404)

        if self._now() >= flow["expires_at"]:
            self._store.pop(flow_id, None)
            return res_builder.build_error_message("SSO login expired", 400)

        try:
            response = self._http_client.post(
                self._token_url(),
                data=self._token_form(flow),
                auth=self._client_auth(),
                headers={"Content-Type": "application/x-www-form-urlencoded"},
                timeout=10,
            )
            payload = response.json()
        except Exception:
            return res_builder.build_error_message("Unable to poll SSO login", 502)

        error = payload.get("error")
        if error in ("authorization_pending", "slow_down"):
            return res_builder.build_response_with_data(
                {
                    "status": "pending",
                    "message": error,
                    "interval": flow["interval"],
                },
                202,
            )

        if response.status_code >= 400:
            self._store.pop(flow_id, None)
            return res_builder.build_error_message(
                self._provider_error_message(payload, "SSO login failed"),
                401,
            )

        access_token = payload.get("access_token")
        if not access_token:
            self._store.pop(flow_id, None)
            return res_builder.build_error_message("SSO login did not return an access token", 401)

        self._store.pop(flow_id, None)
        return self._auth_service.login_oidc(
            access_token,
            expected_namespace=flow.get("requested_namespace"),
        )

    def password(self, username, password, requested_namespace=None):
        if not username or not password:
            return res_builder.build_error_message("Missing SSO username or password", 400)

        try:
            response = self._http_client.post(
                self._token_url(),
                data=self._password_token_form(username, password),
                auth=self._client_auth(),
                headers={"Content-Type": "application/x-www-form-urlencoded"},
                timeout=10,
            )
            payload = response.json()
        except Exception:
            return res_builder.build_error_message("Unable to authenticate with SSO provider", 502)

        if response.status_code >= 400:
            return res_builder.build_error_message(
                self._provider_error_message(
                    payload,
                    "SSO password login failed",
                    extra_sensitive=[password],
                ),
                401,
            )

        access_token = payload.get("access_token")
        if not access_token:
            return res_builder.build_error_message("SSO password login did not return an access token", 401)

        return self._auth_service.login_oidc(
            access_token,
            expected_namespace=requested_namespace,
        )

    def _client_id(self):
        return self._environ.get("OIDC_CLIENT_ID") or self._environ.get("OIDC_AUDIENCE")

    def _client_secret(self):
        return (self._environ.get("OIDC_CLIENT_SECRET") or "").strip()

    def _device_authorization_form(self, challenge):
        form = {
            "client_id": self._client_id(),
            "scope": self._environ.get("OIDC_DEVICE_SCOPE", "openid email profile"),
            "code_challenge": challenge,
            "code_challenge_method": "S256",
        }
        client_secret = self._client_secret()
        if client_secret:
            form["client_secret"] = client_secret
        return form

    def _token_form(self, flow):
        return {
            "grant_type": "urn:ietf:params:oauth:grant-type:device_code",
            "client_id": self._client_id(),
            "device_code": flow["device_code"],
            "code_verifier": flow["verifier"],
        }

    def _password_token_form(self, username, password):
        return {
            "grant_type": "password",
            "client_id": self._client_id(),
            "username": username,
            "password": password,
            "scope": self._environ.get("OIDC_PASSWORD_SCOPE", "openid email profile"),
        }

    def _client_auth(self):
        client_secret = self._client_secret()
        if not client_secret:
            return None
        return (self._client_id(), client_secret)

    def _provider_error_message(self, payload, fallback, extra_sensitive=None):
        message = payload.get("error_description") or payload.get("error") or fallback
        for sensitive in [self._client_secret()] + list(extra_sensitive or []):
            if sensitive:
                message = message.replace(sensitive, "<redacted>")
        return message

    def _device_authorization_url(self):
        return self._environ.get("OIDC_DEVICE_AUTHORIZATION_URL") or (
            f"{self._issuer_url()}/protocol/openid-connect/auth/device"
        )

    def _token_url(self):
        return self._environ.get("OIDC_TOKEN_URL") or (
            f"{self._issuer_url()}/protocol/openid-connect/token"
        )

    def _issuer_url(self):
        issuer = self._environ.get("OIDC_ISSUER_URL")
        if not issuer:
            raise ValueError("missing OIDC_ISSUER_URL")
        return issuer.rstrip("/")

    def _cleanup_expired(self):
        now = self._now()
        expired = [flow_id for flow_id, flow in self._store.items() if now >= flow["expires_at"]]
        for flow_id in expired:
            self._store.pop(flow_id, None)

    def _create_pkce_pair(self):
        verifier = self._base64_url(secrets.token_bytes(32))
        challenge = self._base64_url(hashlib.sha256(verifier.encode("ascii")).digest())
        return verifier, challenge

    def _base64_url(self, value):
        return base64.urlsafe_b64encode(value).decode("ascii").rstrip("=")
