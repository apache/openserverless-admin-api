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

"""Reject OpenWhisk namespace reuse, including deleted subject tombstones."""
import json

import requests

from openserverless.couchdb.couchdb_util import CouchDB
from .kube_client import ProvisioningError


class NamespaceGuard:
    def assert_unused(self, name):
        # Called only after authorization and strict OPS name validation. Use
        # existing CouchDB configuration; no new credentials or database.
        try:
            db = CouchDB()
        except ValueError:
            raise ProvisioningError("Namespace availability could not be verified") from None
        try:
            # Unlike GET /subjects/name (404 for a tombstone), _all_docs with
            # keys retains the deleted row. Never release a used identity just
            # because its WhiskUser or live subject document disappeared.
            rows = self._rows(db, "subjects", {"keys": json.dumps([name])})
            if len(rows) != 1 or not isinstance(rows[0], dict) or rows[0].get("key") != name:
                raise ProvisioningError("Namespace availability could not be verified")
            if rows[0].get("error") != "not_found":
                raise ProvisioningError("User name is already used or retained; administrator review required", 409)
            # Also cover imported/orphaned entities whose subject was purged.
            # OpenWhisk entity and activation IDs are namespace/name. The
            # exclusive ASCII upper bound covers nested packages as well.
            params = {"startkey": json.dumps(name + "/"),
                      "endkey": json.dumps(name + "0"),
                      "inclusive_end": "false", "limit": 1}
            for database in ("whisks", "activations"):
                if self._rows(db, database, params):
                    raise ProvisioningError("User name is already used or retained; administrator review required", 409)
        finally:
            db.db_session.close()

    @staticmethod
    def _rows(db, database, params):
        try:
            response = db.db_session.get(f"{db.db_base}{database}/_all_docs",
                                         params=params, timeout=(2, 3))
            if response.status_code != 200:
                raise ValueError()
            body = response.json()
            if not isinstance(body, dict) or not isinstance(body.get("rows"), list):
                raise ValueError()
            return body["rows"]
        except (requests.RequestException, ValueError):
            # Do not expose backend bodies, credentials or diagnostic URLs.
            raise ProvisioningError("Namespace availability could not be verified") from None
