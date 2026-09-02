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

import base64
import unittest
from unittest.mock import Mock, patch

from openserverless import app
import openserverless.rest.build as build_api


class BuildApiTest(unittest.TestCase):
    def setUp(self):
        self.client = app.test_client()
        self.auth = patch.object(build_api, "authorize", return_value={"login": "sample-user"})
        self.environment = patch.object(
            build_api,
            "authenticated_environment",
            return_value=({"wsk_user_name": "sample-user"}, "sample-user"),
        )
        self.catalog = Mock()
        self.catalog.get.return_value = {
            "kind": "python",
            "source": "registry.example/runtime-python@sha256:abcd",
        }
        self.catalog_patch = patch.object(build_api, "BuildCatalog", return_value=self.catalog)
        self.auth.start()
        self.environment.start()
        self.catalog_patch.start()

    def tearDown(self):
        patch.stopall()

    def payload(self):
        return {
            "builder": "python:3.13",
            "file": base64.b64encode(b"sample-lib==1.0\n").decode(),
        }

    def test_ensure_generates_target_from_authenticated_namespace(self):
        service = Mock()
        service.job_name = "build-sample-user-digest"
        service.get_build_status.return_value = None
        service.build.return_value = (True, service.job_name)
        with patch.object(build_api, "BuildService", return_value=service) as service_class:
            response = self.client.post("/system/api/v1/build/ensure", json=self.payload())

        self.assertEqual(202, response.status_code)
        build_config = service.init.call_args.kwargs["build_config"]
        self.assertTrue(build_config["target"].startswith("sample-user:python-"))
        self.assertNotIn("target", self.payload())
        self.assertEqual(
            {"wsk_user_name": "sample-user"},
            service_class.call_args.kwargs["user_env"],
        )

    def test_ensure_rejects_an_invalid_authenticated_namespace(self):
        with patch.object(
            build_api,
            "authenticated_environment",
            return_value=({"wsk_user_name": "bad;namespace"}, "bad;namespace"),
        ), patch.object(build_api, "BuildService") as service_class:
            response = self.client.post("/system/api/v1/build/ensure", json=self.payload())

        self.assertEqual(401, response.status_code)
        service_class.assert_not_called()

    def test_ensure_rejects_a_file_larger_than_a_config_map_context(self):
        payload = self.payload()
        payload["file"] = base64.b64encode(
            b"a" * (build_api.MAX_BUILD_FILE_BYTES + 1)
        ).decode()

        response = self.client.post("/system/api/v1/build/ensure", json=payload)

        self.assertEqual(400, response.status_code)

    def test_ensure_returns_completed_cached_image(self):
        service = Mock()
        service.get_build_status.return_value = {
            "id": "a" * 64,
            "state": "succeeded",
            "message": "Build completed",
            "image": "node.example:32000/sample-user:python-digest",
        }
        with patch.object(build_api, "BuildService", return_value=service):
            response = self.client.post("/system/api/v1/build/ensure", json=self.payload())

        self.assertEqual(200, response.status_code)
        self.assertEqual("succeeded", response.get_json()["state"])
        service.build.assert_not_called()

    def test_status_rejects_non_digest_identifier(self):
        response = self.client.get("/system/api/v1/build/not-a-digest")

        self.assertEqual(400, response.status_code)


if __name__ == "__main__":
    unittest.main()
