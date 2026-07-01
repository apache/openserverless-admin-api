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
import json
import unittest

from cryptography.hazmat.primitives.asymmetric import padding, rsa
from cryptography.hazmat.primitives import hashes

from openserverless.common.oidc_validator import (
    OidcForbiddenError,
    OidcTokenValidator,
    OidcValidationError,
)


def b64url(data):
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode("ascii")


def int_to_b64url(value):
    length = (value.bit_length() + 7) // 8
    return b64url(value.to_bytes(length, byteorder="big"))


class OidcValidatorTest(unittest.TestCase):

    def setUp(self):
        self.private_key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
        public_numbers = self.private_key.public_key().public_numbers()
        self.jwks = {
            "keys": [
                {
                    "kty": "RSA",
                    "kid": "test-key",
                    "alg": "RS256",
                    "use": "sig",
                    "n": int_to_b64url(public_numbers.n),
                    "e": int_to_b64url(public_numbers.e),
                }
            ]
        }
        self.environ = {
            "OIDC_ISSUER_URL": "http://localhost:8080/realms/openserverless-lab",
            "OIDC_AUDIENCE": "openserverless-admin-api",
            "OIDC_REQUIRED_GROUP": "openserverless-users",
            "OIDC_USERNAME_CLAIM": "preferred_username",
            "OIDC_GROUPS_CLAIM": "groups",
        }

    def token(self, claims, header=None):
        header = header or {"alg": "RS256", "kid": "test-key", "typ": "JWT"}
        encoded_header = b64url(json.dumps(header).encode("utf-8"))
        encoded_claims = b64url(json.dumps(claims).encode("utf-8"))
        signed_data = f"{encoded_header}.{encoded_claims}".encode("ascii")
        signature = self.private_key.sign(
            signed_data,
            padding.PKCS1v15(),
            hashes.SHA256(),
        )
        return f"{encoded_header}.{encoded_claims}.{b64url(signature)}"

    def valid_claims(self):
        return {
            "iss": self.environ["OIDC_ISSUER_URL"],
            "aud": self.environ["OIDC_AUDIENCE"],
            "exp": 2000,
            "preferred_username": "developer.lab",
            "email": "developer.lab@example.test",
            "groups": ["openserverless-users"],
        }

    def validator(self):
        return OidcTokenValidator(self.environ, jwks=self.jwks, now=1000)

    def test_accepts_valid_token(self):
        claims = self.validator().validate(self.token(self.valid_claims()))

        self.assertEqual("developer.lab", claims["preferred_username"])

    def test_rejects_missing_required_group(self):
        claims = self.valid_claims()
        claims["groups"] = []

        with self.assertRaises(OidcForbiddenError):
            self.validator().validate(self.token(claims))

    def test_rejects_wrong_audience(self):
        claims = self.valid_claims()
        claims["aud"] = "other-client"

        with self.assertRaises(OidcValidationError):
            self.validator().validate(self.token(claims))

    def test_rejects_expired_token(self):
        claims = self.valid_claims()
        claims["exp"] = 900

        with self.assertRaises(OidcValidationError):
            self.validator().validate(self.token(claims))


if __name__ == "__main__":
    unittest.main()

