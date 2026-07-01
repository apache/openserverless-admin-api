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
import hashlib
import re

import openserverless.common.validation as validation


class SsoNamespaceMapper:

    def __init__(self, environ):
        self._environ = environ

    def namespace_for(self, claims):
        username_claim = self._environ.get("OIDC_USERNAME_CLAIM", "preferred_username")
        external_username = claims[username_claim]

        namespace_claim = self._environ.get("OIDC_NAMESPACE_CLAIM")
        if namespace_claim and claims.get(namespace_claim):
            namespace = claims[namespace_claim]
            if validation.is_valid_username(namespace):
                return namespace

        if self._preserve_valid() and validation.is_valid_username(external_username):
            return external_username

        return self._normalized_namespace(external_username, claims)

    def _normalized_namespace(self, external_username, claims):
        base = re.sub(r"[^a-z0-9]", "", external_username.lower())
        if len(base) < 5:
            base = f"{base}user"

        suffix = self._suffix(external_username, claims)
        max_len = self._max_len()
        prefix_len = max_len - len(suffix)
        namespace = f"{base[:prefix_len]}{suffix}"

        if validation.is_valid_username(namespace):
            return namespace

        # Defensive fallback for unusual inputs where the base becomes empty.
        namespace = f"user{suffix}"
        if validation.is_valid_username(namespace):
            return namespace

        raise ValueError("Unable to derive a valid namespace from SSO claims")

    def _suffix(self, external_username, claims):
        suffix_len = self._suffix_len()
        source = "|".join(
            [
                claims.get("iss", ""),
                claims.get("sub", ""),
                external_username,
            ]
        )
        return hashlib.sha256(source.encode("utf-8")).hexdigest()[:suffix_len]

    def _preserve_valid(self):
        value = self._environ.get("SSO_NAMESPACE_PRESERVE_VALID", "true")
        return str(value).lower() in ["1", "true", "yes", "on"]

    def _suffix_len(self):
        try:
            value = int(self._environ.get("SSO_NAMESPACE_HASH_LENGTH", 8))
        except (TypeError, ValueError):
            value = 8
        return min(max(value, 6), 16)

    def _max_len(self):
        try:
            value = int(self._environ.get("SSO_NAMESPACE_MAX_LENGTH", 61))
        except (TypeError, ValueError):
            value = 61
        return min(max(value, 13), 61)
