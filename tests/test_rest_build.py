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
from unittest.mock import patch

from openserverless import app
from openserverless.error.api_error import AuthorizationError

AUTH_HEADER = {"Authorization": "Basic dXNlcjpwYXNz"}


def make_user_data(login="myuser", env=None, userenv=None):
    return {
        "login": login,
        "env": env if env is not None else [{"key": "APIHOST", "value": "https://ops.example.test"}],
        "userenv": userenv if userenv is not None else [],
    }


class BuildRouteTestCase(unittest.TestCase):
    """
    Base test case that mocks the two external collaborators used by every
    route in openserverless/rest/build.py: OpenwhiskAuthorize (CouchDB backed
    login) and BuildService (Kubernetes backed build orchestration).
    """

    def setUp(self):
        self.client = app.test_client()

        auth_patcher = patch("openserverless.rest.build.OpenwhiskAuthorize")
        self.mock_authorize_class = auth_patcher.start()
        self.addCleanup(auth_patcher.stop)
        self.mock_authorize = self.mock_authorize_class.return_value

        build_service_patcher = patch("openserverless.rest.build.BuildService")
        self.mock_build_service_class = build_service_patcher.start()
        self.addCleanup(build_service_patcher.stop)
        self.mock_build_service = self.mock_build_service_class.return_value
        self.mock_build_service.id = "550e8400-e29b-41d4-a716-446655440000"
        self.mock_build_service.job_name = "build-myuser-abc123"

    def authorized_as(self, login="myuser", env=None, userenv=None):
        self.mock_authorize.login.return_value = make_user_data(
            login=login, env=env, userenv=userenv
        )

    def unauthorized(self):
        self.mock_authorize.login.side_effect = AuthorizationError("invalid")


class AuthorizationSharedBehaviorTest(BuildRouteTestCase):
    """authorize() is shared by every build route; exercised via build/status."""

    def test_missing_authorization_header_returns_401(self):
        response = self.client.get("/system/api/v1/build/status?id=abc")

        self.assertEqual(401, response.status_code)
        self.assertEqual("ko", response.json["status"])
        self.assertEqual("Missing authorization header", response.json["message"])
        self.mock_authorize.login.assert_not_called()

    def test_invalid_authorization_returns_401(self):
        self.unauthorized()

        response = self.client.get(
            "/system/api/v1/build/status?id=abc", headers=AUTH_HEADER
        )

        self.assertEqual(401, response.status_code)
        self.assertEqual("Invalid authorization", response.json["message"])


class BuildStartTest(BuildRouteTestCase):

    def post(self, json_body=None, headers=AUTH_HEADER):
        if json_body is None:
            return self.client.post(
                "/system/api/v1/build/start",
                data="null",
                content_type="application/json",
                headers=headers,
            )
        return self.client.post(
            "/system/api/v1/build/start", json=json_body, headers=headers
        )

    def test_missing_auth_header_returns_401(self):
        response = self.post({"source": "s", "target": "myuser:tag", "kind": "python"})

        self.assertEqual(401, response.status_code)
        self.mock_build_service_class.assert_not_called()

    def test_empty_user_environment_returns_401(self):
        self.authorized_as(env=[], userenv=[])

        response = self.post({"source": "s", "target": "myuser:tag", "kind": "python"})

        self.assertEqual(401, response.status_code)
        self.assertEqual("User environment not found", response.json["message"])

    def test_no_json_payload_returns_400(self):
        self.authorized_as()

        response = self.post(json_body=None)

        self.assertEqual(400, response.status_code)
        self.assertEqual("No JSON payload provided for build.", response.json["message"])

    def test_missing_source_returns_400(self):
        self.authorized_as()

        response = self.post({"target": "myuser:tag", "kind": "python"})

        self.assertEqual(400, response.status_code)
        self.assertEqual("No source provided for build.", response.json["message"])

    def test_missing_target_returns_400(self):
        self.authorized_as()

        response = self.post({"source": "s", "kind": "python"})

        self.assertEqual(400, response.status_code)
        self.assertEqual("No target provided for build.", response.json["message"])

    def test_missing_kind_returns_400(self):
        self.authorized_as()

        response = self.post({"source": "s", "target": "myuser:tag"})

        self.assertEqual(400, response.status_code)
        self.assertEqual("No kind provided for build.", response.json["message"])

    def test_target_user_mismatch_returns_400_when_strict_check_enabled(self):
        self.authorized_as(login="myuser")

        with patch.dict("os.environ", {"STRICT_USER_CHECK": "true"}):
            response = self.post(
                {"source": "s", "target": "otheruser:tag", "kind": "python"}
            )

        self.assertEqual(400, response.status_code)
        self.assertEqual("Invalid target for the build.", response.json["message"])
        self.mock_build_service_class.assert_not_called()

    def test_target_user_mismatch_allowed_when_strict_check_disabled(self):
        self.authorized_as(login="myuser")
        self.mock_build_service.build.return_value = (True, self.mock_build_service.job_name)

        with patch.dict("os.environ", {"STRICT_USER_CHECK": "false"}):
            response = self.post(
                {"source": "s", "target": "otheruser:tag", "kind": "python"}
            )

        self.assertEqual(200, response.status_code)

    def test_successful_build_returns_200_with_job_details(self):
        self.authorized_as(login="myuser")
        self.mock_build_service.build.return_value = (True, self.mock_build_service.job_name)

        response = self.post({"source": "s", "target": "myuser:tag", "kind": "python"})

        self.assertEqual(200, response.status_code)
        self.assertEqual("ok", response.json["status"])
        self.assertIn(self.mock_build_service.job_name, response.json["message"])
        self.assertEqual(self.mock_build_service.id, response.json["id"])
        self.assertEqual(self.mock_build_service.job_name, response.json["job_name"])

        self.mock_build_service.init.assert_called_once_with(
            build_config={"source": "s", "target": "myuser:tag", "kind": "python"}
        )
        self.mock_build_service.build.assert_called_once_with("myuser:tag")

    def test_build_failure_returns_500_with_service_message(self):
        self.authorized_as(login="myuser")
        self.mock_build_service.build.return_value = (False, "buildkit exploded")

        response = self.post({"source": "s", "target": "myuser:tag", "kind": "python"})

        self.assertEqual(500, response.status_code)
        self.assertEqual("buildkit exploded", response.json["message"])

    def test_build_failure_without_message_uses_default(self):
        self.authorized_as(login="myuser")
        self.mock_build_service.build.return_value = (False, None)

        response = self.post({"source": "s", "target": "myuser:tag", "kind": "python"})

        self.assertEqual(500, response.status_code)
        self.assertEqual("Build process failed.", response.json["message"])


class BuildStatusTest(BuildRouteTestCase):

    def get(self, query_string="", headers=AUTH_HEADER):
        url = "/system/api/v1/build/status"
        if query_string:
            url = f"{url}?{query_string}"
        return self.client.get(url, headers=headers)

    def test_empty_user_environment_returns_401(self):
        self.authorized_as(env=[])

        response = self.get("id=abc")

        self.assertEqual(401, response.status_code)
        self.assertEqual("User environment not found", response.json["message"])

    def test_missing_id_returns_400(self):
        self.authorized_as()

        response = self.get()

        self.assertEqual(400, response.status_code)
        self.assertEqual("No id provided for build status.", response.json["message"])

    def test_job_not_found_returns_404_with_service_message(self):
        self.authorized_as()
        self.mock_build_service.get_job_status.return_value = (False, "Build job not found")

        response = self.get("id=missing-id")

        self.assertEqual(404, response.status_code)
        self.assertEqual("Build job not found", response.json["message"])

    def test_job_not_found_without_message_uses_default(self):
        self.authorized_as()
        self.mock_build_service.get_job_status.return_value = (False, None)

        response = self.get("id=missing-id")

        self.assertEqual(404, response.status_code)
        self.assertEqual("Build job not found.", response.json["message"])

    def test_successful_status_returns_200_with_job_data(self):
        self.authorized_as()
        status_result = {
            "id": "abc",
            "job_name": "build-myuser-abc",
            "phase": "Succeeded",
            "active": 0,
            "succeeded": 1,
            "failed": 0,
            "startTime": "2026-08-15T00:00:00Z",
            "completionTime": "2026-08-15T00:05:00Z",
        }
        self.mock_build_service.get_job_status.return_value = (True, status_result)

        response = self.get("id=abc")

        self.assertEqual(200, response.status_code)
        self.assertEqual("Succeeded", response.json["phase"])
        self.assertEqual("build-myuser-abc", response.json["job_name"])
        self.mock_build_service.get_job_status.assert_called_once_with("abc")


class BuildCleanupTest(BuildRouteTestCase):

    def post(self, json_body=None, headers=AUTH_HEADER):
        if json_body is None:
            return self.client.post(
                "/system/api/v1/build/cleanup",
                data="null",
                content_type="application/json",
                headers=headers,
            )
        return self.client.post(
            "/system/api/v1/build/cleanup", json=json_body, headers=headers
        )

    def test_empty_user_environment_returns_401(self):
        self.authorized_as(env=[])

        response = self.post({})

        self.assertEqual(401, response.status_code)
        self.assertEqual("User environment not found", response.json["message"])

    def test_no_json_payload_returns_400(self):
        self.authorized_as()

        response = self.post(json_body=None)

        self.assertEqual(400, response.status_code)
        self.assertEqual(
            "No JSON payload provided for cleanup.", response.json["message"]
        )

    def test_cleanup_failure_returns_500(self):
        self.authorized_as()
        self.mock_build_service.delete_old_build_jobs.return_value = -1

        response = self.post({})

        self.assertEqual(500, response.status_code)
        self.assertEqual(
            "Failed to clean up old build jobs.", response.json["message"]
        )

    def test_cleanup_uses_default_max_age_hours(self):
        self.authorized_as()
        self.mock_build_service.delete_old_build_jobs.return_value = 3

        response = self.post({})

        self.assertEqual(200, response.status_code)
        self.assertEqual("Cleaned up 3 jobs successfully.", response.json["message"])
        self.mock_build_service.delete_old_build_jobs.assert_called_once_with(
            max_age_hours=24
        )

    def test_cleanup_uses_provided_max_age_hours(self):
        self.authorized_as()
        self.mock_build_service.delete_old_build_jobs.return_value = 0

        response = self.post({"max_age_hours": 2})

        self.assertEqual(200, response.status_code)
        self.mock_build_service.delete_old_build_jobs.assert_called_once_with(
            max_age_hours=2
        )


if __name__ == "__main__":
    unittest.main()
