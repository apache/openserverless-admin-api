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
import datetime
import json
import os
import logging
import secrets
import string
import time
import openserverless.common.response_builder as res_builder
import openserverless.couchdb.bcrypt_util as bu

from openserverless.common.oidc_validator import (
    OidcForbiddenError,
    OidcTokenValidator,
    OidcValidationError,
)
from openserverless.common.sso_namespace import SsoNamespaceMapper
from openserverless.couchdb.couchdb_util import CouchDB
from openserverless.common.kube_api_client import KubeApiClient

USER_META_DBN = "users_metadata"
SSO_PROVIDER_ANNOTATION = "openserverless.apache.org/auth-provider"
SSO_MODE_ANNOTATION = "openserverless.apache.org/auth-mode"
SSO_USERNAME_ANNOTATION = "openserverless.apache.org/sso-username"
SSO_SUB_ANNOTATION = "openserverless.apache.org/sso-sub"
SSO_ISSUER_ANNOTATION = "openserverless.apache.org/sso-issuer"
SSO_DISABLED_ANNOTATION = "openserverless.apache.org/sso-disabled"


class AuthService:

    def __init__(self, environ=os.environ, couch_db=None, kube_client=None):
        self._environ = environ
        self.couch_db = couch_db if couch_db is not None else CouchDB()
        self.kube_client = kube_client if kube_client is not None else KubeApiClient()

    def fetch_user_data(self, login: str):
        logging.info(f"searching for user {login} data")
        try:
            selector = {"selector": {"login": {"$eq": login}}}
            response = self.couch_db.find_doc(USER_META_DBN, json.dumps(selector))

            if response["docs"]:
                docs = list(response["docs"])
                if len(docs) > 0:
                    return docs[0]

            logging.warning(f"OpenServerless metadata for user {login} not found!")
            return None
        except Exception as e:
            logging.error(
                f"failed to query OpenServerless metadata for user {login}. Reason: {e}"
            )
            return None

    def env_to_dict(self, user_data, key="env"):
        """
        extract env from user_data and return it as a dict

        Keyword arguments:
        key -- the key to extract the env from
        """
        body = {}
        if key in user_data:
            envs = list(user_data[key])
        else:
            envs = []

        for env in envs:
            body[env['key']] = env['value']

        return body

    def map_data(self, user_data):
        """
        Map the internal nuvolaris user_data records to the auth response
        """
        resp = {}
        resp["login"] = user_data["login"]
        resp["email"] = user_data["email"]

        if "env" in user_data:
            resp["env"] = user_data["env"]

        if "quota" in user_data:
            resp["quota"] = user_data["quota"]

        return resp

    def login(self, login, password):
        user_data = self.fetch_user_data(login)

        if user_data:
            if bu.verify_password(password, user_data["password"]):
                # if(password == user_data['password']):
                return res_builder.build_response_with_data(self.map_data(user_data))
            else:
                logging.warning(f"password mismatch for user {login}")
                return res_builder.build_error_message(f"Invalid credentials", 401)
        else:
            logging.warning(f"no user {login} found")
            return res_builder.build_error_message(f"Invalid credentials", 401)

    def login_oidc(self, access_token, expected_namespace=None):
        try:
            validator = OidcTokenValidator(self._environ)
            claims = validator.validate(access_token)
        except OidcForbiddenError:
            return res_builder.build_error_message("Forbidden", 403)
        except OidcValidationError as exc:
            logging.warning(f"OIDC token validation failed: {exc}")
            return res_builder.build_error_message("Invalid OIDC token", 401)

        username_claim = self._environ.get("OIDC_USERNAME_CLAIM", "preferred_username")
        external_username = claims[username_claim]
        try:
            login = SsoNamespaceMapper(self._environ).namespace_for(claims)
        except ValueError as exc:
            logging.warning(f"OIDC user {external_username} namespace mapping failed: {exc}")
            return res_builder.build_error_message("Invalid OIDC namespace mapping", 400)

        if expected_namespace and login != expected_namespace:
            logging.warning(
                f"OIDC user {external_username} resolved namespace {login} "
                f"does not match requested namespace {expected_namespace}"
            )
            return res_builder.build_error_message(
                "Authenticated namespace does not match requested workspace",
                403,
            )

        if self.is_sso_login_disabled(login):
            logging.warning(f"OIDC user {external_username} is unbound from namespace {login}")
            return res_builder.build_error_message("Forbidden", 403)

        user_data = self.fetch_user_data(login)

        if not user_data:
            user_data = self.provision_oidc_user_if_enabled(login, external_username, claims)

        if not user_data:
            logging.warning(f"OIDC user {external_username} has no provisioned namespace")
            return res_builder.build_error_message("Namespace not provisioned", 404)

        login_data = self.map_login_data(user_data)
        if "AUTH" not in login_data:
            logging.error(f"OIDC user {login} metadata is missing AUTH")
            return res_builder.build_error_message("Namespace metadata is missing AUTH", 500)

        login_data["LOGIN"] = login
        login_data["NAMESPACE"] = login
        return res_builder.build_response_with_data(login_data)

    def provision_oidc_user_if_enabled(self, login, external_username, claims):
        if not self._is_truthy(self._environ.get("SSO_AUTOPROVISION_ON_LOGIN")):
            return None

        email = claims.get("email")
        if not email:
            logging.warning(f"OIDC user {login} cannot be provisioned without email")
            return None

        if not self.ensure_whisk_user(login, external_username, email, claims):
            return None

        return self.wait_for_user_data(login)

    def ensure_whisk_user(self, login, external_username, email, claims):
        existing_whisk_user = self.kube_client.get_whisk_user(login)
        if existing_whisk_user:
            logging.info(f"WhiskUser for OIDC user {login} already exists")
            return True

        whisk_user = self.build_sso_whisk_user(login, external_username, email, claims)
        if self.kube_client.create_whisk_user(whisk_user):
            logging.info(f"WhiskUser for OIDC user {login} created")
            return True

        # A concurrent login may have created the CR between get and create.
        if self.kube_client.get_whisk_user(login):
            logging.info(f"WhiskUser for OIDC user {login} found after create conflict")
            return True

        logging.error(f"failed to create WhiskUser for OIDC user {login}")
        return False

    def build_sso_whisk_user(self, login, external_username, email, claims):
        auth = self._random_auth()
        password = self._random_secret(24)
        services = self._environ.get("SSO_AUTOPROVISION_DEFAULT_SERVICES", "all")

        whisk_user = {
            "apiVersion": "nuvolaris.org/v1",
            "kind": "WhiskUser",
            "metadata": {
                "name": login,
                "namespace": "nuvolaris",
                "annotations": {
                    SSO_PROVIDER_ANNOTATION: self._environ.get("OIDC_PROVIDER", "keycloak"),
                    SSO_MODE_ANNOTATION: "sso",
                    SSO_USERNAME_ANNOTATION: external_username,
                    SSO_SUB_ANNOTATION: claims.get("sub", ""),
                    SSO_ISSUER_ANNOTATION: claims.get("iss", ""),
                },
            },
            "spec": {
                "email": email,
                "password": password,
                "namespace": login,
                "auth": auth,
            },
        }

        if services == "all":
            whisk_user["spec"]["redis"] = {
                "enabled": True,
                "prefix": login,
                "password": self._random_secret(12),
            }
            whisk_user["spec"]["mongodb"] = {
                "enabled": True,
                "database": login,
                "password": self._random_secret(12),
            }
            whisk_user["spec"]["postgres"] = {
                "enabled": True,
                "database": login,
                "password": self._random_secret(12),
            }
            whisk_user["spec"]["object-storage"] = {
                "password": self._random_secret(40),
                "quota": self._environ.get("SSO_AUTOPROVISION_STORAGE_QUOTA", "auto"),
                "data": {"enabled": True, "bucket": f"{login}-data"},
                "route": {"enabled": True, "bucket": f"{login}-web"},
            }
            whisk_user["spec"]["milvus"] = {
                "enabled": True,
                "database": login,
                "password": self._random_secret(12),
            }

        return whisk_user

    def wait_for_user_data(self, login):
        timeout_seconds = self._int_env("SSO_AUTOPROVISION_TIMEOUT_SECONDS", 120)
        poll_seconds = self._float_env("SSO_AUTOPROVISION_POLL_SECONDS", 2)
        deadline = time.monotonic() + timeout_seconds

        while True:
            user_data = self.fetch_user_data(login)
            if user_data:
                return user_data

            if time.monotonic() >= deadline:
                logging.warning(f"timeout waiting for OIDC namespace {login}")
                return None

            time.sleep(poll_seconds)

    def _random_auth(self):
        return f"{self._random_uuid()}:{self._random_secret(64)}"

    def _random_uuid(self):
        import uuid
        return str(uuid.uuid4())

    def _random_secret(self, length):
        alphabet = string.ascii_letters + string.digits
        return "".join(secrets.choice(alphabet) for _ in range(length))

    def _is_truthy(self, value):
        return str(value or "").lower() in ["1", "true", "yes", "on"]

    def _int_env(self, name, default):
        try:
            return int(self._environ.get(name, default))
        except (TypeError, ValueError):
            return default

    def _float_env(self, name, default):
        try:
            return float(self._environ.get(name, default))
        except (TypeError, ValueError):
            return default

    def is_sso_login_disabled(self, login):
        if not hasattr(self.kube_client, "get_whisk_user"):
            return False

        whisk_user = self.kube_client.get_whisk_user(login)
        annotations = ((whisk_user or {}).get("metadata") or {}).get("annotations") or {}
        return self._is_truthy(annotations.get(SSO_DISABLED_ANNOTATION))

    def map_login_data(self, user_data):
        """
        Map user metadata to the flat string-only shape consumed by ops -login.
        This mirrors the whisk-system/nuv/login system action response.
        """
        body = self.env_to_dict(user_data, "userenv")

        for key, value in self.env_to_dict(user_data, "env").items():
            if key not in body:
                body[key] = value
            else:
                body[f"SYSTEM_{key}"] = value

        return body

    def update_password(self, login, old_password, new_password):
        user_data = self.fetch_user_data(login)

        if user_data:
            if bu.verify_password(old_password, user_data["password"]):
                whisk_user = self.kube_client.get_whisk_user(user_data["login"])

                whisk_user["spec"]["password"] = new_password
                # whisk_user['spec']['password_timestamp'] = datetime.now().isoformat()
                self.kube_client.update_whisk_user(whisk_user)

                return res_builder.build_response_with_data(
                    {"status": "ok", "message": "Password updated"}
                )
            else:
                return res_builder.build_error_message(
                    f"password mismatch for user {login}", 401
                )
        else:
            return res_builder.build_error_message(f"no user {login} found", 401)
