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

from openserverless import app
from http import HTTPStatus
from flask import request

import openserverless.common.response_builder as res_builder
from openserverless.common.utils import env_to_dict
from openserverless.error.api_error import AuthorizationError
from openserverless.impl.builder.build_service import BuildService
from openserverless.common.openwhisk_authorize import OpenwhiskAuthorize

@app.route('/system/build', methods=['POST'])
def build():
    """
    Build Endpoint
    ---
    tags:
      - Build
    responses:
      200:
        description: Build Endpoint Returns Basic Configuration Data used by this API.
        schema:
          $ref: '#/definitions/Message'     
    """

    normalized_headers = {key.lower(): value for key, value in request.headers.items()}
    auth_header = normalized_headers.get('authorization', None)

    if auth_header is None:
        return res_builder.build_error_message("Missing authorization header", 401)

    oa = OpenwhiskAuthorize()
    try:
      user_data = oa.login(auth_header)
      env = env_to_dict(user_data)
      if env is None:
          return res_builder.build_error_message("User environment not found", status_code=HTTPStatus.UNAUTHORIZED)
    
      if (request.json is None):
          return res_builder.build_error_message("No JSON payload provided for build.", status_code=HTTPStatus.BAD_REQUEST)
      
      json_data = request.json
      if 'source' not in json_data:
          return res_builder.build_error_message("No source provided for build.", status_code=HTTPStatus.BAD_REQUEST)
      if 'target' not in json_data:
          return res_builder.build_error_message("No target provided for build.", status_code=HTTPStatus.BAD_REQUEST)
      if 'kind' not in json_data:
          return res_builder.build_error_message("No kind provided for build.", status_code=HTTPStatus.BAD_REQUEST)
      

      # validate the target
      target = json_data.get('target')
      target_user = str(target).split(':')[0]
      if user_data.get('login') != target_user:
         return res_builder.build_error_message("Invalid target for the build.", status_code=HTTPStatus.BAD_REQUEST)

      
      build_service = BuildService(build_config=json_data, user_env=env)
      build_success = build_service.build(json_data.get('target'))  # Replace with your desired image name
      
      if not build_success:
        return res_builder.build_error_message("Build process failed.", status_code=HTTPStatus.INTERNAL_SERVER_ERROR)
      
      return res_builder.build_response_message("Build process initiated successfully.", status_code=HTTPStatus.OK)
    
    except AuthorizationError:
      return res_builder.build_error_message("Invalid authorization", 401)
    
    

@app.route('/system/info')
def info():
    """
    Info Endpoint
    ---
    securityDefinitions:      
        openwhiskBasicAuth:          
    definitions:
      Message:
        type: object
        properties:
          message:
            type: string
          status: 
            type: string
      MessageData:
        type: object
        properties:
          message:
            type: object
          status: 
            type: string
      User:
        type: object
        properties:
          username:
            type: string
          email: 
            type: string
          name:
            type: string
          password:
            type: string
          token:
            type: string
        required:
        - username
        - email
        - name
        - password
        - token    
      LoginUpdateData:
        type: object
        properties:
          password:
            type: string
          new_password:
            type: string
        required:
        - password
        - new_password
      LoginData:
        type: object
        properties:
          login:
            type: string
          password:
            type: string
        required:
        - login
        - password
    tags:
      - Info
    responses:
      200:
        description: Info Endpoint
        schema:
          $ref: '#/definitions/Message'     
    """
    return res_builder.build_response_message("Welcome to OpenServerless system admin API.")

@app.route('/system/config')
def config():
    """
    Info Endpoint
    ---
    tags:
      - Config
    responses:
      200:
        description: Config Endpoint Returns Basic Configuration Data used by this API.
        schema:
          $ref: '#/definitions/Message'     
    """
    config = {
        
    }
    return res_builder.build_response_with_data(config)