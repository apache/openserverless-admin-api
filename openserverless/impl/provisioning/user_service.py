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

"""Externally authorized, create-only OPS tenant provisioning."""
import re
import secrets
import string
import uuid

from openserverless.common.validation import is_valid_username
from .kube_client import ProvisioningError
from .namespace_guard import NamespaceGuard
from .routes import route_context, tenant_routes

SECRET_NAME = "openserverless-user-provisioning-token"
SERVICE_NAMES = ("redis", "mongodb", "postgres", "seaweedfs", "minio", "milvus")
# Infrastructure identities must not be provisioned as ordinary tenants.
RESERVED_USERS = {"openserverless", "whisk", "system", "guest", "default", "controller", "invoker"}


def bearer_token(header):
    if not isinstance(header, str) or len(header) > 8192:
        raise ProvisioningError("Missing or invalid provisioning token", 401)
    parts = header.split()
    if len(parts) != 2 or parts[0].lower() != "bearer" or not parts[1].isascii():
        raise ProvisioningError("Missing or invalid provisioning token", 401)
    return parts[1].encode("ascii")


def random_secret(length=32):
    return "".join(secrets.choice(string.ascii_letters + string.digits) for _ in range(length))


class UserProvisioningService:
    def __init__(self, kube):
        self.kube = kube

    def validate(self, body):
        if not isinstance(body, dict) or set(body) - {"user", "password", "email", "services"}:
            raise ProvisioningError("Invalid user provisioning payload", 400)
        for field in ("user", "password", "email"):
            value = body.get(field)
            if not isinstance(value, str) or not value.strip() or any(ord(c) < 32 or ord(c) == 127 for c in value):
                raise ProvisioningError(f"Invalid or missing {field}", 400)
        user, email = body["user"], body["email"]
        if not is_valid_username(user) or user in RESERVED_USERS:
            raise ProvisioningError("Invalid or reserved user name", 400)
        # The operator embeds email in its JSON metadata template. Restrict to
        # an ordinary ASCII dot-atom address (no quoted local part or escapes).
        local, separator, domain = email.rpartition("@")
        local_atom = r"[A-Za-z0-9!#$%&'*+/=?^_`{|}~-]+"
        domain_label = r"[A-Za-z0-9](?:[A-Za-z0-9-]{0,61}[A-Za-z0-9])?"
        if (len(email) > 254 or not separator or len(local) > 64
                or not re.fullmatch(local_atom + r"(?:\." + local_atom + r")*", local)
                or not re.fullmatch(domain_label + r"(?:\." + domain_label + r")+", domain)):
            raise ProvisioningError("Invalid email", 400)
        # CouchDB uses bcrypt; do not silently truncate UTF-8 passwords.
        try:
            encoded_password = body["password"].encode("utf-8")
            email.encode("utf-8")
        except UnicodeError:
            raise ProvisioningError("Invalid UTF-8 field", 400) from None
        if len(encoded_password) > 72:
            raise ProvisioningError("Password exceeds 72 UTF-8 bytes", 400)
        selection = body.get("services", "all")
        if not isinstance(selection, str):
            raise ProvisioningError("Invalid services selection", 400)
        selected = [item.strip() for item in selection.split(",")]
        if (not all(selected) or len(set(selected)) != len(selected)
                or ("all" in selected and len(selected) != 1)
                or any(item not in SERVICE_NAMES + ("all",) for item in selected)):
            raise ProvisioningError("Invalid services selection", 400)
        return selected

    def provision(self, body):
        selection = self.validate(body)
        user = body["user"]
        if self.kube.existing_user(user) is not None:
            raise ProvisioningError("User already exists", 409)
        cluster = self.kube.cluster()
        components = cluster.get("spec", {}).get("components")
        if not isinstance(components, dict) or any(
            not isinstance(components.get(name, False), bool) for name in SERVICE_NAMES
        ):
            raise ProvisioningError("Cluster service configuration unavailable")
        available = [name for name in SERVICE_NAMES if components.get(name) is True]
        if "seaweedfs" in available and "minio" in available:
            raise ProvisioningError("Ambiguous object-storage configuration")
        services = available if selection == ["all"] else [name for name in SERVICE_NAMES if name in selection]
        if any(name not in available for name in services):
            raise ProvisioningError("Requested service is not enabled in this cluster", 400)
        # Match the backend identifier limits before submitting an unusable CR.
        # FerretDB appends "_ferretdb" to PostgreSQL role/database identifiers.
        if "mongodb" in services and len(user) > 54:
            raise ProvisioningError("MongoDB users must not exceed 54 characters", 400)
        if any(name in services for name in ("seaweedfs", "minio")) and len(user) > 58:
            raise ProvisioningError("Object-storage users must not exceed 58 characters", 400)
        context = route_context(self.kube.apihost_ingress())
        streamer = self.kube.streamer_service() is not None
        # Validate hostname and route construction before creating anything.
        tenant_routes(user, context, services, streamer, "preflight")
        NamespaceGuard().assert_unused(user)
        spec = {"namespace": user, "email": body["email"], "password": body["password"],
                "auth": f"{uuid.uuid4()}:{random_secret(64)}"}
        for name in ("redis", "mongodb", "postgres", "milvus"):
            if name in services:
                spec[name] = {"enabled": True, "password": random_secret(),
                              "prefix" if name == "redis" else "database": user}
        if "seaweedfs" in services or "minio" in services:
            spec["object-storage"] = {"password": random_secret(40), "quota": "auto",
                                      "data": {"enabled": True, "bucket": f"{user}-data"},
                                      "route": {"enabled": True, "bucket": f"{user}-web"}}
        resource = {"apiVersion": "openserverless.org/v1", "kind": "WhiskUser",
                    "metadata": {"name": user, "namespace": "openserverless"}, "spec": spec}
        try:
            created = self.kube.create_user(resource)
        except ProvisioningError as exc:
            if exc.status == 409:
                raise ProvisioningError("User already exists", 409) from None
            raise
        uid = created.get("metadata", {}).get("uid")
        if not isinstance(uid, str) or not uid:
            raise ProvisioningError("User creation could not be confirmed; administrator review required")
        try:
            for route in tenant_routes(user, context, services, streamer, uid):
                self.kube.create_route(route)
        except ProvisioningError:
            # Do not roll back a tenant which the operator may already be using.
            raise ProvisioningError("User created but route setup failed; administrator review required") from None
        return {"status": "ok", "message": "User provisioning accepted", "user": user,
                "provisioning_status": "pending", "services": services}
