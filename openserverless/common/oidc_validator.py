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
import time

import requests
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.asymmetric import padding, rsa


class OidcValidationError(Exception):
    pass


class OidcForbiddenError(Exception):
    pass


def _b64url_decode(value):
    value += "=" * (-len(value) % 4)
    return base64.urlsafe_b64decode(value.encode("ascii"))


def _json_b64url_decode(value):
    return json.loads(_b64url_decode(value))


def _int_b64url_decode(value):
    return int.from_bytes(_b64url_decode(value), byteorder="big")


class OidcTokenValidator:

    def __init__(self, environ, jwks=None, now=None):
        self._environ = environ
        self._jwks = jwks
        self._now = now

    def _get_required(self, key):
        value = self._environ.get(key)
        if not value:
            raise OidcValidationError(f"missing OIDC configuration: {key}")
        return value

    def _get_jwks(self):
        if self._jwks is not None:
            return self._jwks

        jwks_url = self._get_required("OIDC_JWKS_URL")
        response = requests.get(jwks_url, timeout=10)
        response.raise_for_status()
        self._jwks = response.json()
        return self._jwks

    def _find_jwk(self, kid):
        for jwk in self._get_jwks().get("keys", []):
            if jwk.get("kid") == kid:
                return jwk
        raise OidcValidationError("no matching JWK found for token kid")

    def _public_key(self, jwk):
        if jwk.get("kty") != "RSA":
            raise OidcValidationError("unsupported JWK key type")

        public_numbers = rsa.RSAPublicNumbers(
            e=_int_b64url_decode(jwk["e"]),
            n=_int_b64url_decode(jwk["n"]),
        )
        return public_numbers.public_key()

    def _verify_signature(self, token, header):
        parts = token.split(".")
        signed_data = f"{parts[0]}.{parts[1]}".encode("ascii")
        signature = _b64url_decode(parts[2])
        jwk = self._find_jwk(header.get("kid"))
        public_key = self._public_key(jwk)

        try:
            public_key.verify(
                signature,
                signed_data,
                padding.PKCS1v15(),
                hashes.SHA256(),
            )
        except Exception as exc:
            raise OidcValidationError("invalid token signature") from exc

    def _validate_time_claims(self, claims):
        now = self._now if self._now is not None else int(time.time())
        leeway = int(self._environ.get("OIDC_CLOCK_LEEWAY_SECONDS", "30"))

        exp = claims.get("exp")
        if exp is None or int(exp) < now - leeway:
            raise OidcValidationError("token expired")

        nbf = claims.get("nbf")
        if nbf is not None and int(nbf) > now + leeway:
            raise OidcValidationError("token is not valid yet")

    def _validate_issuer(self, claims):
        expected = self._get_required("OIDC_ISSUER_URL")
        if claims.get("iss") != expected:
            raise OidcValidationError("invalid issuer")

    def _validate_audience(self, claims):
        expected = self._get_required("OIDC_AUDIENCE")
        audience = claims.get("aud")
        if isinstance(audience, list) and expected in audience:
            return
        if audience == expected:
            return
        raise OidcValidationError("invalid audience")

    def _validate_required_group(self, claims):
        required_group = self._environ.get("OIDC_REQUIRED_GROUP")
        if not required_group:
            return

        groups_claim = self._environ.get("OIDC_GROUPS_CLAIM", "groups")
        groups = claims.get(groups_claim, [])
        if isinstance(groups, str):
            groups = [groups]

        if required_group not in groups:
            raise OidcForbiddenError("missing required group")

    def validate(self, token):
        if not token:
            raise OidcValidationError("missing access token")

        parts = token.split(".")
        if len(parts) != 3:
            raise OidcValidationError("invalid token format")

        header = _json_b64url_decode(parts[0])
        claims = _json_b64url_decode(parts[1])

        if header.get("alg") != "RS256":
            raise OidcValidationError("unsupported token algorithm")

        self._verify_signature(token, header)
        self._validate_issuer(claims)
        self._validate_audience(claims)
        self._validate_time_claims(claims)
        self._validate_required_group(claims)

        username_claim = self._environ.get("OIDC_USERNAME_CLAIM", "preferred_username")
        if not claims.get(username_claim):
            raise OidcValidationError(f"missing username claim: {username_claim}")

        return claims

