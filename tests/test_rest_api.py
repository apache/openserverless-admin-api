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

from openserverless import app


class InfoEndpointTest(unittest.TestCase):

    def setUp(self):
        self.client = app.test_client()

    def test_info_returns_welcome_message(self):
        response = self.client.get("/system/info")

        self.assertEqual(200, response.status_code)
        self.assertEqual("ok", response.json["status"])
        self.assertEqual(
            "Welcome to OpenServerless system admin API.", response.json["message"]
        )


class ConfigEndpointTest(unittest.TestCase):

    def setUp(self):
        self.client = app.test_client()

    def test_config_returns_configuration_data(self):
        response = self.client.get("/system/config")

        self.assertEqual(200, response.status_code)
        self.assertEqual({}, response.json)


if __name__ == "__main__":
    unittest.main()
