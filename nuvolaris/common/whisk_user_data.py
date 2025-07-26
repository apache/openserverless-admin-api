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
import uuid
import random
import string


class WhiskUserData:
    """Wraps a whisk user with a convenience class

    Returns:
        _type_: WhiskUserData
    """

    _data = {}

    def __init__(self, username, email, password, auth):
        self._data["username"] = username
        self._data["email"] = email
        self._data["password"] = password
        self._data["auth"] = auth

        self._data["block_storage_enabled"] = False
        self._data["redis_enabled"] = False
        self._data["mongodb_enabled"] = False
        self._data["postgres_enabled"] = False

    def auth_generator(self):
        """
        Builds an OpenWhisk Compliant AUTH token
        """
        uid = str(uuid.uuid4())
        key = "".join(
            random.choice(string.ascii_letters + string.digits) for _ in range(64)
        )

        return f"{uid}:{key}"

    def pwd_generator(self):
        """
        Builds an OpenWhisk Compliant AUTH token
        """
        return "".join(
            random.choice(string.ascii_letters + string.digits) for _ in range(16)
        )

    def with_block_storage(self, minio_quota, minio_secret):
        """enable block storage

        Args:
            minio_quota (string): block storage quota in MB
            minio_secret (string): secret to be used when configured over MINIO
        """
        self._data["minio_quota"] = minio_quota
        self._data["minio_secret"] = minio_secret
        self._data["block_storage_enabled"] = True

    def with_redis(self, redis_quota, redis_prefix, redis_password):
        """enable redis config

        Args:
            redis_quota (string): Redis user quota
            redis_prefix (string): Redis Prefix
            redis_password (string): Password
        """
        self._data["redis_quota"] = redis_quota
        self._data["redis_prefix"] = redis_prefix
        self._data["redis_password"] = redis_password
        self._data["redis_enabled"] = True

    def with_mongodb(self, mongodb_quota, mongodb_password):
        """enable mongodb config

        Args:
            mongodb_quota (string): MongoDB user quota
            redis_password (string): Password
        """
        self._data["mongodb_quota"] = mongodb_quota
        self._data["mongodb_password"] = mongodb_password
        self._data["mongodb_enabled"] = True

    def with_posgtres(self, pg_quota, pg_password):
        """enable postgres config

        Args:
            pg_quota (string): Posgtres user quota
            pg_password (string): Password
        """
        self._data["postgres_quota"] = pg_quota
        self._data["postgres_password"] = pg_password
        self._data["postgres_enabled"] = True

    def generate_whisk_user_resource(self):
        """
        Return a dictionary Object representing a whisk-user.yaml to create a user with OW namespace and MINIO buckets
        param: username
        param: email
        param: password
        param: minio_quota
        param: minio_secret (use pwd_generator())
        param: auth Openwhisk Compliant auth (use auth_generator())
        """

        wsku = {
            "apiVersion": "nuvolaris.org/v1",
            "kind": "WhiskUser",
            "metadata": {"name": self._data["username"], "namespace": "nuvolaris"},
            "spec": {
                "email": self._data["email"],
                "password": self._data["password"],
                "namespace": self._data["username"],
                "auth": self._data["auth"],
            },
        }

        if self._data["block_storage_enabled"]:
            wsku["spec"]["object-storage"] = {
                "password": self._data["minio_secret"],
                "quota": f"{self._data['minio_quota']}",
                "data": {"enabled": True, "bucket": f"{self._data['username']}-data"},
                "route": {"enabled": True, "bucket": f"{self._data['username']}-web"},
            }

        if self._data["redis_enabled"]:
            wsku["spec"]["redis"] = {
                "enabled": True,
                "quota": f"{self._data['redis_quota']}",
                "prefix": self._data["redis_prefix"],
                "password": self._data["redis_password"],
            }

        if self._data["mongodb_enabled"]:
            wsku["spec"]["mongodb"] = {
                "enabled": True,
                "database": self._data["username"],
                "quota": f"{self._data['mongodb_quota']}",
                "password": self._data["mongodb_password"],
            }

        if self._data["postgres_enabled"]:
            wsku["spec"]["postgres"] = {
                "enabled": True,
                "database": self._data["username"],
                "quota": f"{self._data['postgres_quota']}",
                "password": self._data["postgres_password"],
            }

        return wsku
