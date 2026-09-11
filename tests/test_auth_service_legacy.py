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
from unittest.mock import Mock, patch

from openserverless import app
from openserverless.impl.auth.auth_service import AuthService


class LegacyAuthenticationTest(unittest.TestCase):
    def setUp(self):
        self.user = {
            "login": "legacyuser",
            "email": "legacy@example.test",
            "password": "stored-password-hash",
            "env": [{"key": "AUTH", "value": "uuid:key"}],
            "quota": {"memory": 256},
        }
        self.couch = Mock()
        self.couch.find_doc.return_value = {"docs": [self.user]}
        self.kube = Mock()
        self.service = AuthService(
            environ={"SSO_AUTOPROVISION_ON_LOGIN": "true"},
            couch_db=self.couch,
            kube_client=self.kube,
        )

    @patch("openserverless.impl.auth.auth_service.OidcTokenValidator")
    @patch("openserverless.impl.auth.auth_service.bu.verify_password", return_value=True)
    def test_password_login_keeps_metadata_response_and_does_not_use_oidc(self, verify, validator):
        with app.app_context():
            response = self.service.login("legacyuser", "legacy-password")
        self.assertEqual(200, response.status_code)
        self.assertEqual(
            {key: self.user[key] for key in ("login", "email", "env", "quota")},
            response.json,
        )
        verify.assert_called_once_with("legacy-password", "stored-password-hash")
        validator.assert_not_called()
        self.assertEqual([], self.kube.mock_calls)

    @patch("openserverless.impl.auth.auth_service.bu.verify_password", return_value=False)
    def test_invalid_password_keeps_401_and_does_not_provision(self, verify):
        with app.app_context():
            response = self.service.login("legacyuser", "wrong-password")
        self.assertEqual(401, response.status_code)
        self.assertEqual([], self.kube.mock_calls)

    def test_missing_password_user_keeps_401_and_does_not_provision(self):
        self.couch.find_doc.return_value = {"docs": []}
        with app.app_context():
            response = self.service.login("missinguser", "password")
        self.assertEqual(401, response.status_code)
        self.assertEqual([], self.kube.mock_calls)

    @patch("openserverless.impl.auth.auth_service.bu.verify_password", return_value=True)
    def test_password_update_keeps_existing_whisk_user_fields(self, verify):
        resource = {"spec": {"password": "old", "namespace": "legacyuser", "redis": {"enabled": True}}}
        self.kube.get_whisk_user.return_value = resource
        with app.app_context():
            response = self.service.update_password("legacyuser", "old-password", "new-password")
        self.assertEqual(200, response.status_code)
        self.kube.update_whisk_user.assert_called_once_with({
            "spec": {"password": "new-password", "namespace": "legacyuser", "redis": {"enabled": True}}
        })

    @patch("openserverless.rest.auth.AuthService")
    def test_existing_password_route_keeps_argument_dispatch(self, service_class):
        service_class.return_value.login.return_value = ({"legacy": "response"}, 200)
        with app.test_client() as client:
            response = client.post("/system/api/v1/auth", json={"login": "legacyuser", "password": "password"})
        self.assertEqual(200, response.status_code)
        self.assertEqual({"legacy": "response"}, response.json)
        service_class.return_value.login.assert_called_once_with("legacyuser", "password")
