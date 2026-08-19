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
import os
import tempfile
import unittest
from datetime import datetime, timezone
from unittest.mock import patch

from openserverless.impl.builder.build_service import BuildService


class BuildServiceTestCase(unittest.TestCase):
    """
    Base test case that mocks the only external collaborator of BuildService
    (KubeApiClient) and clears REGISTRY_HOST so registry resolution is
    deterministic across the environment running the tests.
    """

    def setUp(self):
        kube_patcher = patch("openserverless.impl.builder.build_service.KubeApiClient")
        self.mock_kube_client_class = kube_patcher.start()
        self.addCleanup(kube_patcher.stop)
        self.mock_kube_client = self.mock_kube_client_class.return_value
        self.mock_kube_client.get_config_map.return_value = None
        self.mock_kube_client.get_jobs.return_value = []

        env_patcher = patch.dict(os.environ, {"REGISTRY_HOST": ""})
        env_patcher.start()
        self.addCleanup(env_patcher.stop)

    def make_service(self, user_env=None):
        return BuildService(user_env=user_env or {"wsk_user_name": "myuser"})


class GetRegistryHostTest(BuildServiceTestCase):

    def test_env_var_takes_precedence(self):
        with patch.dict(os.environ, {"REGISTRY_HOST": "env-registry:5000"}):
            service = self.make_service()
            self.assertEqual("env-registry:5000", service.get_registry_host())

    def test_user_env_used_when_no_env_var(self):
        service = self.make_service(
            user_env={"wsk_user_name": "myuser", "REGISTRY_HOST": "user-registry:5000"}
        )

        self.assertEqual("user-registry:5000", service.get_registry_host())

    def test_config_map_annotation_used_as_fallback(self):
        service = self.make_service()
        self.mock_kube_client.get_config_map.return_value = {
            "metadata": {"annotations": {"registry_host": "cm-registry:5000"}}
        }

        self.assertEqual("cm-registry:5000", service.get_registry_host())

    def test_default_fallback_when_nothing_configured(self):
        service = self.make_service()

        self.assertEqual("nuvolaris-registry-svc:5000", service.get_registry_host())


class GetRegistryAuthTest(BuildServiceTestCase):

    def test_default_secret_name_when_no_custom_secret(self):
        service = self.make_service()

        self.assertEqual("registry-pull-secret", service.get_registry_auth())

    def test_existing_secret_reference_returned_as_is(self):
        service = self.make_service(
            user_env={"wsk_user_name": "myuser", "REGISTRY_SECRET": "my-existing-secret"}
        )

        self.assertEqual("my-existing-secret", service.get_registry_auth())

    def test_custom_credentials_create_registry_secret(self):
        service = self.make_service(
            user_env={"wsk_user_name": "myuser", "REGISTRY_SECRET": "bob:pw"}
        )
        self.mock_kube_client.post_secret.return_value = {
            "metadata": {"name": "reg-myuser-abcde"}
        }

        auth = service.get_registry_auth()

        self.assertEqual("reg-myuser-abcde", auth)
        self.assertTrue(service.custom_registry_auth)
        self.mock_kube_client.post_secret.assert_called_once()

    def test_failed_secret_creation_falls_back_to_default(self):
        service = self.make_service(
            user_env={"wsk_user_name": "myuser", "REGISTRY_SECRET": "bob:pw"}
        )
        self.mock_kube_client.post_secret.return_value = None

        self.assertEqual("registry-pull-secret", service.get_registry_auth())
        self.assertFalse(service.custom_registry_auth)


class CreateDockerFileTest(BuildServiceTestCase):

    def test_without_requirements_file_key(self):
        service = self.make_service()
        service.build_config = {"source": "python:3.12"}

        content = service.create_docker_file()

        self.assertEqual("FROM python:3.12\n\n", content)

    def test_with_file_key_includes_copy_and_extend(self):
        service = self.make_service()
        service.build_config = {"source": "python:3.12", "file": "base64data"}

        content = service.create_docker_file(requirements="requirements.txt")

        self.assertIn("COPY requirements.txt /tmp/requirements.txt", content)
        self.assertIn("RUN /bin/extend", content)


class GetRequirementsFileFromKindTest(BuildServiceTestCase):

    def test_known_kinds_map_to_expected_files(self):
        service = self.make_service()
        expected = {
            "python": "requirements.txt",
            "nodejs": "package.json",
            "php": "composer.json",
            "java": "pom.xml",
            "go": "go.mod",
            "ruby": "Gemfile",
            "dotnet": "project.json",
        }
        for kind, filename in expected.items():
            with self.subTest(kind=kind):
                service.build_config = {"kind": kind}
                self.assertEqual(filename, service.get_requirements_file_from_kind())

    def test_unsupported_kind_raises(self):
        service = self.make_service()
        service.build_config = {"kind": "cobol"}

        with self.assertRaises(ValueError):
            service.get_requirements_file_from_kind()


class CheckBuildDirTest(BuildServiceTestCase):

    def test_missing_directory_returns_false(self):
        service = self.make_service()

        self.assertFalse(service.check_build_dir("/nonexistent/path/xyz"))

    def test_directory_without_dockerfile_returns_false(self):
        service = self.make_service()
        with tempfile.TemporaryDirectory() as tmpdir:
            self.assertFalse(service.check_build_dir(tmpdir))

    def test_directory_with_dockerfile_returns_true(self):
        service = self.make_service()
        with tempfile.TemporaryDirectory() as tmpdir:
            with open(os.path.join(tmpdir, "Dockerfile"), "w") as f:
                f.write("FROM scratch\n")
            self.assertTrue(service.check_build_dir(tmpdir))


class CreateBuildJobTest(BuildServiceTestCase):

    def test_default_registry_prefixes_image_name(self):
        service = self.make_service()
        service.registry_host = "myregistry:5000"
        service.registry_auth = "registry-pull-secret"
        service.custom_registry_auth = False

        manifest = service.create_build_job("myuser:tag")

        self.assertEqual(service.job_name, manifest["metadata"]["name"])
        containers = manifest["spec"]["template"]["spec"]["containers"]
        self.assertIn("myregistry:5000/myuser:tag", containers[0]["args"][0])

    def test_custom_registry_auth_does_not_prefix_image_name(self):
        service = self.make_service()
        service.registry_host = "myregistry:5000"
        service.registry_auth = "custom-secret"
        service.custom_registry_auth = True

        manifest = service.create_build_job("myuser:tag")

        containers = manifest["spec"]["template"]["spec"]["containers"]
        self.assertIn("name=myuser:tag,push=true", containers[0]["args"][0])
        self.assertNotIn("myregistry:5000/myuser:tag", containers[0]["args"][0])

    def test_docker_config_secret_name_matches_registry_auth(self):
        service = self.make_service()
        service.registry_host = "myregistry:5000"
        service.registry_auth = "custom-secret"
        service.custom_registry_auth = True

        manifest = service.create_build_job("myuser:tag")

        volumes = manifest["spec"]["template"]["spec"]["volumes"]
        docker_config_volume = next(v for v in volumes if v["name"] == "docker-config")
        self.assertEqual("custom-secret", docker_config_volume["secret"]["secretName"])


class InitTest(BuildServiceTestCase):

    def test_creates_buildkitd_configmap_when_missing(self):
        service = self.make_service()
        self.mock_kube_client.get_config_map.return_value = None

        service.init(build_config={"source": "s", "target": "t", "kind": "python"})

        self.mock_kube_client.post_config_map.assert_called_once_with(
            cm_name="nuvolaris-buildkitd-conf",
            file_or_dir="deploy/buildkit/buildkitd.toml",
            namespace="nuvolaris",
        )

    def test_skips_creation_when_configmap_exists(self):
        service = self.make_service()
        self.mock_kube_client.get_config_map.return_value = {
            "metadata": {"name": "nuvolaris-buildkitd-conf"}
        }

        service.init(build_config={"source": "s", "target": "t", "kind": "python"})

        self.mock_kube_client.post_config_map.assert_not_called()


class GetJobStatusTest(BuildServiceTestCase):

    def test_returns_false_when_job_not_found(self):
        service = self.make_service()
        self.mock_kube_client.get_job.return_value = None

        success, result = service.get_job_status("some-build-id")

        self.assertFalse(success)
        self.assertEqual("Build job not found", result)

    def test_reports_succeeded_phase(self):
        service = self.make_service()
        self.mock_kube_client.get_job.return_value = {
            "status": {
                "succeeded": 1, "failed": 0, "active": 0,
                "startTime": "t0", "completionTime": "t1",
            }
        }

        success, result = service.get_job_status("abc")

        self.assertTrue(success)
        self.assertEqual("Succeeded", result["phase"])

    def test_reports_failed_phase(self):
        service = self.make_service()
        self.mock_kube_client.get_job.return_value = {
            "status": {"succeeded": 0, "failed": 1, "active": 0}
        }

        _, result = service.get_job_status("abc")

        self.assertEqual("Failed", result["phase"])

    def test_reports_running_phase(self):
        service = self.make_service()
        self.mock_kube_client.get_job.return_value = {
            "status": {"succeeded": 0, "failed": 0, "active": 1}
        }

        _, result = service.get_job_status("abc")

        self.assertEqual("Running", result["phase"])

    def test_reports_pending_phase(self):
        service = self.make_service()
        self.mock_kube_client.get_job.return_value = {"status": {}}

        _, result = service.get_job_status("abc")

        self.assertEqual("Pending", result["phase"])


class DeleteOldBuildJobsTest(BuildServiceTestCase):

    def _job(self, name, completed=True, completion_time=None):
        conditions = [{"type": "Complete", "status": "True"}] if completed else []
        return {
            "metadata": {"name": name},
            "status": {"conditions": conditions, "completionTime": completion_time},
        }

    def test_returns_minus_one_when_jobs_lookup_fails(self):
        service = self.make_service()
        self.mock_kube_client.get_jobs.return_value = None

        self.assertEqual(-1, service.delete_old_build_jobs())

    def test_deletes_old_completed_jobs(self):
        service = self.make_service()
        old_time = "2000-01-01T00:00:00Z"
        self.mock_kube_client.get_jobs.return_value = [
            self._job("build-myuser-old", completion_time=old_time)
        ]
        self.mock_kube_client.delete_job.return_value = True

        count = service.delete_old_build_jobs(max_age_hours=24)

        self.assertEqual(1, count)
        self.mock_kube_client.delete_job.assert_called_once_with(job_name="build-myuser-old")

    def test_keeps_recent_completed_jobs(self):
        service = self.make_service()
        recent_time = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
        self.mock_kube_client.get_jobs.return_value = [
            self._job("build-myuser-recent", completion_time=recent_time)
        ]

        count = service.delete_old_build_jobs(max_age_hours=24)

        self.assertEqual(0, count)
        self.mock_kube_client.delete_job.assert_not_called()

    def test_ignores_incomplete_jobs(self):
        service = self.make_service()
        self.mock_kube_client.get_jobs.return_value = [
            self._job("build-myuser-running", completed=False)
        ]

        count = service.delete_old_build_jobs(max_age_hours=24)

        self.assertEqual(0, count)
        self.mock_kube_client.delete_job.assert_not_called()


class CleanupBuildResourcesTest(BuildServiceTestCase):

    def test_deletes_configmap_always(self):
        service = self.make_service()
        self.mock_kube_client.delete_config_map.return_value = True
        service.custom_registry_auth = False

        service._cleanup_build_resources()

        self.mock_kube_client.delete_config_map.assert_called_once_with(cm_name=service.cm)
        self.mock_kube_client.delete_secret.assert_not_called()

    def test_deletes_custom_secret_when_flagged(self):
        service = self.make_service()
        self.mock_kube_client.delete_config_map.return_value = True
        service.custom_registry_auth = True
        service.registry_auth = "custom-secret"

        service._cleanup_build_resources()

        self.mock_kube_client.delete_secret.assert_called_once_with(secret_name="custom-secret")


class BuildTestCase(BuildServiceTestCase):
    """Shared happy-path collaborator defaults for the full build() flow."""

    def setUp(self):
        super().setUp()
        self.mock_kube_client.get_secret.return_value = {
            "metadata": {"name": "registry-pull-secret"}
        }
        self.mock_kube_client.post_config_map.return_value = {"metadata": {"name": "cm"}}
        self.mock_kube_client.post_job.return_value = {"metadata": {"name": "job"}}
        self.mock_kube_client.wait_for_init_container_completion.return_value = True
        self.mock_kube_client.delete_config_map.return_value = True

    def run_build(self, build_config):
        service = self.make_service()
        service.init(build_config=build_config)
        return service, service.build(build_config["target"])


class BuildHappyPathTest(BuildTestCase):

    def test_successful_build_returns_job_name(self):
        service, (success, message) = self.run_build(
            {"source": "python:3.12", "target": "myuser:tag", "kind": "python"}
        )

        self.assertTrue(success)
        self.assertEqual(service.job_name, message)
        self.mock_kube_client.post_job.assert_called_once()
        self.mock_kube_client.wait_for_init_container_completion.assert_called_once()
        self.mock_kube_client.delete_config_map.assert_called_once_with(cm_name=service.cm)


class BuildFailureTest(BuildTestCase):

    def test_missing_secret_fails(self):
        self.mock_kube_client.get_secret.return_value = None

        _, (success, message) = self.run_build(
            {"source": "s", "target": "myuser:tag", "kind": "python"}
        )

        self.assertFalse(success)
        self.assertIn("is not configured", message)

    def test_invalid_base64_requirements_fails(self):
        _, (success, message) = self.run_build(
            {"source": "s", "target": "myuser:tag", "kind": "python", "file": "not-valid-base64!!"}
        )

        self.assertFalse(success)
        self.assertEqual("Requirements file must be valid base64-encoded data", message)

    def test_config_map_creation_failure(self):
        self.mock_kube_client.post_config_map.return_value = None

        _, (success, message) = self.run_build(
            {"source": "s", "target": "myuser:tag", "kind": "python"}
        )

        self.assertFalse(success)
        self.assertEqual("Failed to create ConfigMap for build context", message)

    def test_job_creation_failure_still_cleans_up(self):
        self.mock_kube_client.post_job.return_value = None

        service, (success, message) = self.run_build(
            {"source": "s", "target": "myuser:tag", "kind": "python"}
        )

        self.assertFalse(success)
        self.assertIn("Failed to create job", message)
        self.mock_kube_client.delete_config_map.assert_called_once_with(cm_name=service.cm)


if __name__ == "__main__":
    unittest.main()
