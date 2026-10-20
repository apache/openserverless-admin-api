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
import copy
import unittest
from unittest.mock import Mock, patch

from openserverless import app
from openserverless.impl.auth.auth_service import AuthService


class SsoIdentityBindingTest(unittest.TestCase):
    def setUp(self):
        self.claims = {"iss": "https://issuer.test/realm", "sub": "owner-id",
                       "preferred_username": "tenantuser", "email": "user@example.test"}
        self.resource = {"metadata": {"name": "tenantuser", "uid": "tenant-uid", "annotations": {
            "openserverless.apache.org/sso-issuer": self.claims["iss"],
            "openserverless.apache.org/sso-sub": self.claims["sub"],
        }}, "spec": {"namespace": "tenantuser", "auth": "uuid:key"}}
        self.metadata = {"login": "tenantuser", "email": "user@example.test",
                         "env": [{"key": "AUTH", "value": "uuid:key"}]}
        self.couch = Mock()
        self.couch.find_doc.return_value = {"docs": [self.metadata]}
        self.kube = Mock()
        self.kube.get_whisk_user.return_value = self.resource
        self.service = AuthService(environ={}, couch_db=self.couch, kube_client=self.kube)

    def login(self, claims=None, **kwargs):
        with patch("openserverless.impl.auth.auth_service.OidcTokenValidator") as validator:
            validator.return_value.validate.return_value = claims if claims is not None else self.claims
            with app.app_context():
                return self.service.login_oidc("signed-token", **kwargs)

    def denied(self, response, status=403):
        self.assertEqual(status, response.status_code)
        self.assertNotIn("AUTH", response.json)
        self.kube.update_whisk_user.assert_not_called()

    def test_matching_immutable_identity_receives_own_credentials(self):
        response = self.login()
        self.assertEqual(200, response.status_code)
        self.assertEqual("uuid:key", response.json["AUTH"])

    def test_legacy_namespace_without_binding_is_denied(self):
        self.resource["metadata"]["annotations"] = {}
        self.denied(self.login())
        self.couch.find_doc.assert_not_called()
        self.kube.create_whisk_user.assert_not_called()

    def test_different_identity_same_username_is_denied(self):
        self.denied(self.login({**self.claims, "sub": "different-owner"}))

    def test_different_bound_issuer_is_denied(self):
        self.resource["metadata"]["annotations"]["openserverless.apache.org/sso-issuer"] = "https://other.test"
        self.denied(self.login())

    def test_missing_and_non_string_identity_claims_are_denied(self):
        for key in ("iss", "sub"):
            for value in (None, "", " ", 123, ["owner-id"]):
                with self.subTest(key=key, value=value):
                    self.denied(self.login({**self.claims, key: value}), 401)

    def test_partial_binding_is_denied(self):
        for key in ("openserverless.apache.org/sso-issuer", "openserverless.apache.org/sso-sub"):
            resource = copy.deepcopy(self.resource)
            del resource["metadata"]["annotations"][key]
            self.kube.get_whisk_user.return_value = resource
            with self.subTest(key=key):
                self.denied(self.login())

    def test_disabled_matching_binding_is_denied(self):
        self.resource["metadata"]["annotations"]["openserverless.apache.org/sso-disabled"] = "true"
        self.denied(self.login())

    def test_explicit_namespace_claim_does_not_bypass_binding(self):
        self.service._environ = {"OIDC_NAMESPACE_CLAIM": "workspace"}
        self.denied(self.login({**self.claims, "preferred_username": "attackeruser",
                               "workspace": "tenantuser", "sub": "attacker-id"}))

    def test_requested_namespace_does_not_bypass_binding(self):
        self.denied(self.login({**self.claims, "sub": "attacker-id"}, expected_namespace="tenantuser"))

    def test_missing_whisk_user_does_not_expose_orphan_metadata(self):
        self.kube.get_whisk_user.return_value = None
        self.denied(self.login())

    def test_revoked_binding_after_metadata_lookup_is_denied(self):
        revoked = copy.deepcopy(self.resource)
        revoked["metadata"]["annotations"]["openserverless.apache.org/sso-disabled"] = "true"
        self.kube.get_whisk_user.side_effect = [self.resource, revoked]
        self.denied(self.login())

    def test_stale_credentials_after_recreation_are_not_returned(self):
        recreated = copy.deepcopy(self.resource)
        recreated["metadata"]["uid"] = "recreated-tenant-uid"
        self.kube.get_whisk_user.side_effect = [self.resource, recreated]
        self.denied(self.login())

    def test_existing_metadata_credentials_remain_authoritative(self):
        self.resource["spec"]["auth"] = "old-spec:old-key"
        response = self.login()
        self.assertEqual(200, response.status_code)
        self.assertEqual("uuid:key", response.json["AUTH"])

    def test_existing_resource_during_provisioning_must_match_identity(self):
        self.resource["metadata"]["annotations"]["openserverless.apache.org/sso-sub"] = "other-id"
        self.assertFalse(self.service.ensure_whisk_user("tenantuser", "tenantuser", "u@example.test", self.claims))
        self.kube.create_whisk_user.assert_not_called()

    def test_create_conflict_rejects_other_owner_and_legacy_and_disabled(self):
        variants = [copy.deepcopy(self.resource) for _ in range(3)]
        variants[0]["metadata"]["annotations"]["openserverless.apache.org/sso-sub"] = "other-id"
        variants[1]["metadata"]["annotations"] = {}
        variants[2]["metadata"]["annotations"]["openserverless.apache.org/sso-disabled"] = "true"
        for resource in variants:
            with self.subTest(resource=resource):
                self.kube.get_whisk_user.side_effect = [None, resource]
                self.kube.create_whisk_user.return_value = False
                self.assertFalse(self.service.ensure_whisk_user("tenantuser", "tenantuser", "u@example.test", self.claims))

    def test_create_conflict_accepts_same_bound_owner(self):
        self.kube.get_whisk_user.side_effect = [None, self.resource]
        self.kube.create_whisk_user.return_value = False
        self.assertTrue(self.service.ensure_whisk_user("tenantuser", "tenantuser", "u@example.test", self.claims))


if __name__ == "__main__":
    unittest.main()
