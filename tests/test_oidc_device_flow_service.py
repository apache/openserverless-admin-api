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
import unittest

import openserverless.common.response_builder as res_builder
from openserverless import app
from openserverless.impl.auth.oidc_device_flow_service import OidcDeviceFlowService


class FakeResponse:

    def __init__(self, payload, status_code=200):
        self._payload = payload
        self.status_code = status_code

    def json(self):
        return self._payload


class FakeHttpClient:

    def __init__(self, responses):
        self.responses = list(responses)
        self.calls = []

    def post(self, url, data=None, auth=None, headers=None, timeout=None):
        self.calls.append(
            {
                "url": url,
                "data": data,
                "auth": auth,
                "headers": headers,
                "timeout": timeout,
            }
        )
        return self.responses.pop(0)


class FakeAuthService:

    def __init__(self):
        self.tokens = []

    def login_oidc(self, access_token, expected_namespace=None):
        self.tokens.append(
            {
                "access_token": access_token,
                "expected_namespace": expected_namespace,
            }
        )
        return res_builder.build_response_with_data(
            {
                "LOGIN": "michelem",
                "NAMESPACE": "michelem",
                "AUTH": "uuid:key",
            }
        )


class OidcDeviceFlowServiceTest(unittest.TestCase):

    def setUp(self):
        self.environ = {
            "OIDC_ISSUER_URL": "https://keycloak.example.test/realms/openserverless-lab",
            "OIDC_AUDIENCE": "openserverless-admin-api",
        }

    def test_start_creates_backend_flow_without_returning_oidc_details(self):
        store = {}
        http_client = FakeHttpClient(
            [
                FakeResponse(
                    {
                        "device_code": "device-secret",
                        "user_code": "ABCD-EFGH",
                        "verification_uri": "https://keycloak.example.test/device",
                        "verification_uri_complete": "https://keycloak.example.test/device?user_code=ABCD-EFGH",
                        "expires_in": 600,
                        "interval": 5,
                    }
                )
            ]
        )
        service = OidcDeviceFlowService(
            environ=self.environ,
            http_client=http_client,
            auth_service=FakeAuthService(),
            store=store,
            now=lambda: 1000,
        )

        with app.app_context():
            response = service.start(requested_namespace="michelem")

        self.assertEqual(200, response.status_code)
        self.assertEqual("ABCD-EFGH", response.json["user_code"])
        self.assertEqual("https://keycloak.example.test/device?user_code=ABCD-EFGH", response.json["verification_uri_complete"])
        self.assertIn("flow_id", response.json)
        self.assertNotIn("device_code", response.json)
        self.assertNotIn("code_verifier", response.json)
        self.assertEqual(1, len(store))
        self.assertEqual("device-secret", next(iter(store.values()))["device_code"])
        self.assertEqual("michelem", next(iter(store.values()))["requested_namespace"])

        start_call = http_client.calls[0]
        self.assertEqual(
            "https://keycloak.example.test/realms/openserverless-lab/protocol/openid-connect/auth/device",
            start_call["url"],
        )
        self.assertEqual("openserverless-admin-api", start_call["data"]["client_id"])
        self.assertEqual("S256", start_call["data"]["code_challenge_method"])
        self.assertIsNone(start_call["auth"])
        self.assertNotIn("client_secret", start_call["data"])

    def test_start_uses_client_secret_for_confidential_client_without_returning_it(self):
        store = {}
        http_client = FakeHttpClient(
            [
                FakeResponse(
                    {
                        "device_code": "device-secret",
                        "user_code": "ABCD-EFGH",
                        "verification_uri": "https://keycloak.example.test/device",
                        "expires_in": 600,
                    }
                )
            ]
        )
        environ = dict(self.environ)
        environ["OIDC_CLIENT_SECRET"] = "super-secret"
        service = OidcDeviceFlowService(
            environ=environ,
            http_client=http_client,
            auth_service=FakeAuthService(),
            store=store,
            now=lambda: 1000,
        )

        with app.app_context():
            response = service.start()

        self.assertEqual(200, response.status_code)
        self.assertNotIn("client_secret", response.json)
        self.assertNotIn("device_code", response.json)
        self.assertNotIn("code_verifier", response.json)
        self.assertEqual("super-secret", http_client.calls[0]["data"]["client_secret"])

    def test_poll_returns_pending_without_exposing_token(self):
        store = {
            "flow-1": {
                "device_code": "device-secret",
                "verifier": "verifier",
                "expires_at": 2000,
                "interval": 5,
            }
        }
        http_client = FakeHttpClient([FakeResponse({"error": "authorization_pending"}, 400)])
        service = OidcDeviceFlowService(
            environ=self.environ,
            http_client=http_client,
            auth_service=FakeAuthService(),
            store=store,
            now=lambda: 1000,
        )

        with app.app_context():
            response = service.poll("flow-1")

        self.assertEqual(202, response.status_code)
        self.assertEqual("pending", response.json["status"])
        self.assertEqual("authorization_pending", response.json["message"])
        self.assertIn("flow-1", store)

    def test_poll_exchanges_token_and_returns_openserverless_login(self):
        store = {
            "flow-1": {
                "device_code": "device-secret",
                "verifier": "verifier",
                "expires_at": 2000,
                "interval": 5,
            }
        }
        auth_service = FakeAuthService()
        http_client = FakeHttpClient([FakeResponse({"access_token": "oidc-token"})])
        service = OidcDeviceFlowService(
            environ=self.environ,
            http_client=http_client,
            auth_service=auth_service,
            store=store,
            now=lambda: 1000,
        )

        with app.app_context():
            response = service.poll("flow-1")

        self.assertEqual(200, response.status_code)
        self.assertEqual("michelem", response.json["NAMESPACE"])
        self.assertEqual(
            [{"access_token": "oidc-token", "expected_namespace": None}],
            auth_service.tokens,
        )
        self.assertNotIn("flow-1", store)

        token_call = http_client.calls[0]
        self.assertEqual(
            "https://keycloak.example.test/realms/openserverless-lab/protocol/openid-connect/token",
            token_call["url"],
        )
        self.assertEqual("device-secret", token_call["data"]["device_code"])
        self.assertEqual("verifier", token_call["data"]["code_verifier"])
        self.assertIsNone(token_call["auth"])

    def test_poll_uses_http_basic_auth_for_confidential_client(self):
        store = {
            "flow-1": {
                "device_code": "device-secret",
                "verifier": "verifier",
                "expires_at": 2000,
                "interval": 5,
            }
        }
        environ = dict(self.environ)
        environ["OIDC_CLIENT_SECRET"] = "super-secret"
        auth_service = FakeAuthService()
        http_client = FakeHttpClient([FakeResponse({"access_token": "oidc-token"})])
        service = OidcDeviceFlowService(
            environ=environ,
            http_client=http_client,
            auth_service=auth_service,
            store=store,
            now=lambda: 1000,
        )

        with app.app_context():
            response = service.poll("flow-1")

        self.assertEqual(200, response.status_code)
        token_call = http_client.calls[0]
        self.assertEqual(("openserverless-admin-api", "super-secret"), token_call["auth"])
        self.assertEqual("openserverless-admin-api", token_call["data"]["client_id"])
        self.assertNotIn("client_secret", token_call["data"])
        self.assertNotIn("flow-1", store)

    def test_provider_errors_do_not_leak_client_secret(self):
        store = {}
        environ = dict(self.environ)
        environ["OIDC_CLIENT_SECRET"] = "super-secret"
        http_client = FakeHttpClient(
            [
                FakeResponse(
                    {
                        "error": "invalid_client",
                        "error_description": "bad client secret super-secret",
                    },
                    401,
                )
            ]
        )
        service = OidcDeviceFlowService(
            environ=environ,
            http_client=http_client,
            auth_service=FakeAuthService(),
            store=store,
            now=lambda: 1000,
        )

        with app.app_context():
            response = service.start()

        self.assertEqual(502, response.status_code)
        self.assertNotIn("super-secret", str(response.json))
        self.assertIn("<redacted>", response.json["message"])

    def test_poll_passes_requested_namespace_to_oidc_login(self):
        store = {
            "flow-1": {
                "device_code": "device-secret",
                "verifier": "verifier",
                "expires_at": 2000,
                "interval": 5,
                "requested_namespace": "michelem",
            }
        }
        auth_service = FakeAuthService()
        http_client = FakeHttpClient([FakeResponse({"access_token": "oidc-token"})])
        service = OidcDeviceFlowService(
            environ=self.environ,
            http_client=http_client,
            auth_service=auth_service,
            store=store,
            now=lambda: 1000,
        )

        with app.app_context():
            response = service.poll("flow-1")

        self.assertEqual(200, response.status_code)
        self.assertEqual(
            [{"access_token": "oidc-token", "expected_namespace": "michelem"}],
            auth_service.tokens,
        )

    def test_poll_expired_flow(self):
        store = {
            "flow-1": {
                "device_code": "device-secret",
                "verifier": "verifier",
                "expires_at": 1000,
                "interval": 5,
            }
        }
        service = OidcDeviceFlowService(
            environ=self.environ,
            http_client=FakeHttpClient([]),
            auth_service=FakeAuthService(),
            store=store,
            now=lambda: 1000,
        )

        with app.app_context():
            response = service.poll("flow-1")

        self.assertEqual(400, response.status_code)
        self.assertNotIn("flow-1", store)


if __name__ == "__main__":
    unittest.main()
