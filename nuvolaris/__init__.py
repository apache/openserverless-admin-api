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
__version__ = '0.1.0'

import logging
import os

from flask import Flask
from flasgger import Swagger
from flask_cors import CORS
from dotenv import load_dotenv

load_dotenv()

swagger_config = {
    "headers": [
    ],
    "specs": [
        {
            "endpoint": 'apispec_1',
            "route": '/system/apispec_1.json',
            "rule_filter": lambda rule: True,  # all in
            "model_filter": lambda tag: True,  # all in
            "title":"OpenServerless Admin Api",
            "version":"0.1.0"
        }
    ],
    "static_url_path": "/system/flasgger_static",
    "swagger_ui": True,
    "specs_route": "/system/apidocs/",
    "securityDefinitions": {
        "openwhiskBasicAuth": {
            "type": "apiKey",
            "name": "Authorization",
            "in": "header",
            "description": "Token to add to header Authorization"
        }
    },
    "security": [
        {"openwhiskBasicAuth": []}
    ],
    "auth": dict({})
}

logging.basicConfig(level=logging.DEBUG)
app = Flask(__name__)
cors = CORS(app)
swagger = Swagger(app=app,config=swagger_config,merge=True)

listen_port = os.environ.get("LISTEN_PORT", "5000")

import nuvolaris.rest.api
import nuvolaris.rest.auth

if __name__ == "nuvolaris":
    from waitress import serve
    serve(app, host="0.0.0.0", port=listen_port)