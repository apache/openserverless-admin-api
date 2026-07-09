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

import openserverless.common.validation as validation
from openserverless.common.sso_namespace import SsoNamespaceMapper


class SsoNamespaceMapperTest(unittest.TestCase):

    def claims(self, preferred_username):
        return {
            "iss": "http://localhost:8080/realms/openserverless-lab",
            "sub": "keycloak-subject",
            "preferred_username": preferred_username,
        }

    def test_preserves_valid_namespace(self):
        namespace = SsoNamespaceMapper({}).namespace_for(self.claims("devel"))

        self.assertEqual("devel", namespace)

    def test_normalizes_invalid_username_with_hash_suffix(self):
        namespace = SsoNamespaceMapper({}).namespace_for(self.claims("developer.lab"))

        self.assertTrue(namespace.startswith("developerlab"))
        self.assertTrue(validation.is_valid_username(namespace))
        self.assertLessEqual(len(namespace), 61)

    def test_hash_suffix_keeps_colliding_bases_unique(self):
        first = SsoNamespaceMapper({}).namespace_for(
            {
                "iss": "issuer",
                "sub": "first",
                "preferred_username": "developer.lab",
            }
        )
        second = SsoNamespaceMapper({}).namespace_for(
            {
                "iss": "issuer",
                "sub": "second",
                "preferred_username": "developer_lab",
            }
        )

        self.assertNotEqual(first, second)

    def test_can_use_explicit_namespace_claim_when_valid(self):
        namespace = SsoNamespaceMapper(
            {"OIDC_NAMESPACE_CLAIM": "openserverless_namespace"}
        ).namespace_for(
            {
                "preferred_username": "developer.lab",
                "openserverless_namespace": "customns",
            }
        )

        self.assertEqual("customns", namespace)


if __name__ == "__main__":
    unittest.main()
