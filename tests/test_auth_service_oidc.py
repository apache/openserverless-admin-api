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
from unittest.mock import patch

from openserverless import app
from openserverless.impl.auth.auth_service import AuthService


class FakeCouchDB:

    def __init__(self, docs):
        self.docs = docs

    def find_doc(self, db_name, selector):
        return {"docs": self.docs}


class SequencedCouchDB:

    def __init__(self, docs_by_call):
        self.docs_by_call = list(docs_by_call)
        self.calls = 0

    def find_doc(self, db_name, selector):
        index = min(self.calls, len(self.docs_by_call) - 1)
        self.calls += 1
        return {"docs": self.docs_by_call[index]}


class FakeKubeClient:

    def __init__(self, existing=None, create_result=True):
        self.existing = existing
        self.create_result = create_result
        self.created = []

    def get_whisk_user(self, username):
        return self.existing

    def create_whisk_user(self, whisk_user):
        self.created.append(whisk_user)
        return self.create_result


class AuthServiceOidcTest(unittest.TestCase):

    def service(self, docs, environ=None, kube_client=None):
        env = {
            "OIDC_USERNAME_CLAIM": "preferred_username",
        }
        if environ:
            env.update(environ)
        return AuthService(
            environ=env,
            couch_db=FakeCouchDB(docs),
            kube_client=kube_client if kube_client is not None else object(),
        )

    @patch("openserverless.impl.auth.auth_service.OidcTokenValidator")
    def test_oidc_login_returns_ops_login_data(self, validator_class):
        validator_class.return_value.validate.return_value = {
            "preferred_username": "devel",
        }
        service = self.service(
            [
                {
                    "login": "devel",
                    "email": "devel@example.test",
                    "env": [
                        {"key": "AUTH", "value": "uuid:key"},
                        {"key": "APIHOST", "value": "https://ops.example.test"},
                        {"key": "SHARED", "value": "system-value"},
                    ],
                    "userenv": [
                        {"key": "SHARED", "value": "user-value"},
                    ],
                }
            ]
        )

        with app.app_context():
            response = service.login_oidc("token")

        self.assertEqual(200, response.status_code)
        self.assertEqual("uuid:key", response.json["AUTH"])
        self.assertEqual("https://ops.example.test", response.json["APIHOST"])
        self.assertEqual("devel", response.json["LOGIN"])
        self.assertEqual("devel", response.json["NAMESPACE"])
        self.assertEqual("user-value", response.json["SHARED"])
        self.assertEqual("system-value", response.json["SYSTEM_SHARED"])
        self.assertNotIn("quota", response.json)

    @patch("openserverless.impl.auth.auth_service.OidcTokenValidator")
    def test_oidc_login_returns_404_when_namespace_is_missing(self, validator_class):
        validator_class.return_value.validate.return_value = {
            "preferred_username": "missing.lab",
        }
        service = self.service([])

        with app.app_context():
            response = service.login_oidc("token")

        self.assertEqual(404, response.status_code)
        self.assertEqual("ko", response.json["status"])

    @patch("openserverless.impl.auth.auth_service.OidcTokenValidator")
    def test_oidc_login_returns_403_when_sso_binding_is_disabled(self, validator_class):
        validator_class.return_value.validate.return_value = {
            "preferred_username": "devel",
        }
        service = self.service(
            [
                {
                    "login": "devel",
                    "email": "devel@example.test",
                    "env": [{"key": "AUTH", "value": "uuid:key"}],
                }
            ],
            kube_client=FakeKubeClient(
                existing={
                    "metadata": {
                        "annotations": {
                            "openserverless.apache.org/sso-disabled": "true",
                        },
                    },
                },
            ),
        )

        with app.app_context():
            response = service.login_oidc("token")

        self.assertEqual(403, response.status_code)
        self.assertEqual("ko", response.json["status"])

    @patch("openserverless.impl.auth.auth_service.OidcTokenValidator")
    def test_oidc_login_autoprovisions_whisk_user_when_enabled(self, validator_class):
        validator_class.return_value.validate.return_value = {
            "iss": "http://issuer.test",
            "sub": "keycloak-subject",
            "preferred_username": "ssouser",
            "email": "sso.user@example.test",
        }
        kube_client = FakeKubeClient()
        service = AuthService(
            environ={
                "OIDC_USERNAME_CLAIM": "preferred_username",
                "SSO_AUTOPROVISION_ON_LOGIN": "true",
                "SSO_AUTOPROVISION_TIMEOUT_SECONDS": "1",
                "SSO_AUTOPROVISION_POLL_SECONDS": "0",
            },
            couch_db=SequencedCouchDB(
                [
                    [],
                    [
                        {
                            "login": "ssouser",
                            "email": "sso.user@example.test",
                            "env": [
                                {"key": "AUTH", "value": "uuid:key"},
                                {"key": "APIHOST", "value": "https://ops.example.test"},
                            ],
                        }
                    ],
                ]
            ),
            kube_client=kube_client,
        )

        with app.app_context():
            response = service.login_oidc("token")

        self.assertEqual(200, response.status_code)
        self.assertEqual("uuid:key", response.json["AUTH"])
        self.assertEqual("ssouser", response.json["LOGIN"])
        self.assertEqual("ssouser", response.json["NAMESPACE"])
        self.assertEqual(1, len(kube_client.created))

        whisk_user = kube_client.created[0]
        self.assertEqual("WhiskUser", whisk_user["kind"])
        self.assertEqual("ssouser", whisk_user["metadata"]["name"])
        self.assertEqual("ssouser", whisk_user["spec"]["namespace"])
        self.assertEqual("sso.user@example.test", whisk_user["spec"]["email"])
        self.assertIn(":", whisk_user["spec"]["auth"])
        self.assertNotEqual("", whisk_user["spec"]["password"])
        self.assertEqual(
            "keycloak",
            whisk_user["metadata"]["annotations"][
                "openserverless.apache.org/auth-provider"
            ],
        )

    @patch("openserverless.impl.auth.auth_service.OidcTokenValidator")
    def test_oidc_login_rejects_namespace_mismatch_before_autoprovision(self, validator_class):
        validator_class.return_value.validate.return_value = {
            "iss": "http://issuer.test",
            "sub": "developer-subject",
            "preferred_username": "developer.lab",
            "email": "developer.lab@example.test",
        }
        kube_client = FakeKubeClient()
        service = AuthService(
            environ={
                "OIDC_USERNAME_CLAIM": "preferred_username",
                "SSO_AUTOPROVISION_ON_LOGIN": "true",
            },
            couch_db=FakeCouchDB([]),
            kube_client=kube_client,
        )

        with app.app_context():
            response = service.login_oidc("token", expected_namespace="michelem")

        self.assertEqual(403, response.status_code)
        self.assertEqual("ko", response.json["status"])
        self.assertEqual(
            "Authenticated namespace does not match requested workspace",
            response.json["message"],
        )
        self.assertEqual([], kube_client.created)

    @patch("openserverless.impl.auth.auth_service.OidcTokenValidator")
    def test_oidc_login_autoprovisions_normalized_namespace(self, validator_class):
        validator_class.return_value.validate.return_value = {
            "iss": "http://issuer.test",
            "sub": "developer-subject",
            "preferred_username": "developer.lab",
            "email": "developer.lab@example.test",
        }
        kube_client = FakeKubeClient()
        service = AuthService(
            environ={
                "OIDC_USERNAME_CLAIM": "preferred_username",
                "SSO_AUTOPROVISION_ON_LOGIN": "true",
                "SSO_AUTOPROVISION_TIMEOUT_SECONDS": "1",
                "SSO_AUTOPROVISION_POLL_SECONDS": "0",
            },
            couch_db=SequencedCouchDB(
                [
                    [],
                    [
                        {
                            "login": "developerlab4717c17e",
                            "email": "developer.lab@example.test",
                            "env": [{"key": "AUTH", "value": "uuid:key"}],
                        }
                    ],
                ]
            ),
            kube_client=kube_client,
        )

        with app.app_context():
            response = service.login_oidc("token")

        self.assertEqual(200, response.status_code)
        self.assertEqual("developerlab4717c17e", response.json["LOGIN"])
        self.assertEqual("developerlab4717c17e", response.json["NAMESPACE"])
        self.assertEqual(1, len(kube_client.created))
        self.assertEqual("developerlab4717c17e", kube_client.created[0]["metadata"]["name"])
        self.assertEqual(
            "developer.lab",
            kube_client.created[0]["metadata"]["annotations"][
                "openserverless.apache.org/sso-username"
            ],
        )

    @patch("openserverless.impl.auth.auth_service.OidcTokenValidator")
    def test_oidc_login_returns_500_when_auth_is_missing(self, validator_class):
        validator_class.return_value.validate.return_value = {
            "preferred_username": "developer.lab",
        }
        service = self.service(
            [
                {
                    "login": "developer.lab",
                    "email": "developer.lab@example.test",
                    "env": [{"key": "APIHOST", "value": "https://ops.example.test"}],
                }
            ]
        )

        with app.app_context():
            response = service.login_oidc("token")

        self.assertEqual(500, response.status_code)
        self.assertEqual("ko", response.json["status"])


if __name__ == "__main__":
    unittest.main()
