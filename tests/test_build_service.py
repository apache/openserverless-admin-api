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

import unittest

from openserverless.impl.builder.build_service import BuildService


class FakeKubeClient:
    def __init__(self, job=None):
        self.job = job

    def get_config_map(self, name):
        return {
            "metadata": {
                "annotations": {
                    "registry_push_host": "registry.svc:5000",
                    "registry_pull_host": "node.example:32000",
                }
            }
        }

    def get_job(self, name):
        return self.job


class BuildServiceTest(unittest.TestCase):
    def service(self, job=None):
        return BuildService(
            user_env={"wsk_user_name": "sample-user"},
            build_id="a" * 64,
            kube_client=FakeKubeClient(job),
        )

    def test_separates_push_and_pull_registry_hosts(self):
        service = self.service()

        self.assertEqual("registry.svc:5000", service.get_registry_push_host())
        self.assertEqual("node.example:32000", service.get_registry_pull_host())
        self.assertEqual(
            "node.example:32000/sample-user:python-digest",
            service.action_image("sample-user:python-digest"),
        )

    def test_reports_completed_job_with_pullable_image(self):
        job = {
            "metadata": {
                "annotations": {
                    "openserverless.apache.org/target-image": "sample-user:python-digest"
                }
            },
            "status": {
                "conditions": [{"type": "Complete", "status": "True"}]
            },
        }

        status = self.service(job).get_build_status()

        self.assertEqual("succeeded", status["state"])
        self.assertEqual(
            "node.example:32000/sample-user:python-digest", status["image"]
        )

    def test_reports_failed_job_without_image(self):
        job = {
            "metadata": {"annotations": {}},
            "status": {
                "conditions": [
                    {
                        "type": "Failed",
                        "status": "True",
                        "reason": "BackoffLimitExceeded",
                    }
                ]
            },
        }

        status = self.service(job).get_build_status()

        self.assertEqual("failed", status["state"])
        self.assertIsNone(status["image"])

    def test_build_job_uses_a_versioned_multiarch_buildkit_image(self):
        service = self.service()
        service.registry_auth = "registry-pull-secret-int"

        manifest = service.create_build_job("sample-user:python-digest")

        container = manifest["spec"]["template"]["spec"]["containers"][0]
        self.assertEqual("moby/buildkit:v0.30.0-rootless", container["image"])

    def test_build_job_rejects_a_target_with_shell_syntax(self):
        with self.assertRaisesRegex(ValueError, "Invalid target image"):
            self.service().create_build_job("sample:tag;touch-/tmp/unsafe")


if __name__ == "__main__":
    unittest.main()
