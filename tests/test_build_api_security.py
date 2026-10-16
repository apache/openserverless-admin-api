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
from unittest.mock import patch, Mock
from openserverless import app
from openserverless.rest import build
from openserverless.impl.builder.build_service import BuildService

class BuildApiSecurityTest(unittest.TestCase):
    def setUp(self):
        self.client = app.test_client()
        self.payload = {"source":"runtime:python", "target":"alpha:release", "kind":"python"}

    @patch.object(build, "env_to_dict", return_value={"SYNTHETIC":"value"})
    @patch.object(build, "authorize", return_value={"login":"alpha"})
    def test_invalid_inputs_rejected_before_worker_creation(self, authorize, env):
        with patch.dict(build.os.environ, {"STRICT_USER_CHECK":"true"}), patch.object(BuildService, "__init__", return_value=None) as initialize:
            for key, value in (("target","alpha:ok;id"), ("target","beta:release"),
                               ("target","alpha:ok$(id)"), ("source","runtime:python\nRUN id")):
                response = self.client.post("/system/api/v1/build/start",json={**self.payload,key:value})
                self.assertEqual(400,response.status_code)
            initialize.assert_not_called()

    @patch.object(build, "env_to_dict", return_value={"SYNTHETIC":"value"})
    @patch.object(build, "authorize", return_value={"login":"alpha"})
    def test_valid_request_keeps_response_contract(self, authorize, env):
        service = Mock(id="synthetic-id", job_name="build-alpha-test")
        service.build.return_value = (True,"build-alpha-test")
        with patch.object(build,"BuildService") as factory:
            factory.valid_image_target.side_effect = BuildService.valid_image_target
            factory.valid_source_image.side_effect = BuildService.valid_source_image
            factory.return_value = service
            response = self.client.post("/system/api/v1/build/start",json=self.payload)
        self.assertEqual(200,response.status_code)
        self.assertEqual("build-alpha-test",response.json["job_name"])
        service.init.assert_called_once_with(build_config=self.payload)
        service.build.assert_called_once_with("alpha:release")
