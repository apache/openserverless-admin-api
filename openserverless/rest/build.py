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
from flask import request, Response

import openserverless.common.response_builder as res_builder
from openserverless.common.utils import env_to_dict
from openserverless.error.api_error import AuthorizationError
from openserverless.impl.builder.build_service import BuildService
from openserverless.common.openwhisk_authorize import OpenwhiskAuthorize

def authorize() -> Response | dict:
    normalized_headers = {key.lower(): value for key, value in request.headers.items()}
    auth_header = normalized_headers.get('authorization', None)

    if auth_header is None:
        return res_builder.build_error_message("Missing authorization header", 401)

    oa = OpenwhiskAuthorize()
    try:
        user_data = oa.login(auth_header)
        return user_data
        
        
    except AuthorizationError:
      return res_builder.build_error_message("Invalid authorization", 401)

@app.route('/system/api/v1/build/start', methods=['POST'])
def build():
    """
    Build Endpoint
    ---
    tags:
      - Build
    summary: Build an image using the provided source, target, and kind.
    description: This endpoint triggers a build process based on the provided parameters.
    operationId: buildImage
    security:
        - openwhiskBasicAuth: []
    consumes:
        - application/json
    parameters:
      - in: body
        name: BuildRequest
        required: true
        schema:
          type: object
          properties:
            source:
              type: string
              description: Source for the build
            target:
              type: string
              description: Target for the build
            kind:
              type: string
              description: Kind of the build
    responses:
      200:
        description: Build process initiated successfully.
        schema:
          $ref: '#/definitions/Message'
      400:
        description: Bad Request. Missing or invalid parameters.
        schema:
          $ref: '#/definitions/Message'
      401:
        description: Unauthorized. Invalid or missing authorization header.
        schema:
          $ref: '#/definitions/Message'
      500:
        description: Internal Server Error. Build process failed.
        schema:
          $ref: '#/definitions/Message'
    """    
    auth_result = authorize()
    if isinstance(auth_result, Response):
      return auth_result
    
    env = env_to_dict(auth_result)
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
    wsk_user_name = auth_result.get('login','').lower()
    target = json_data.get('target')
    target_user = str(target).split(':')[0]
    if wsk_user_name != target_user:
        return res_builder.build_error_message("Invalid target for the build.", status_code=HTTPStatus.BAD_REQUEST)

    env['wsk_user_name'] = wsk_user_name
    build_service = BuildService(user_env=env)
    build_service.init(build_config=json_data)
    build_success = build_service.build(json_data.get('target'))  # Replace with your desired image name
    
    if not build_success:
        return res_builder.build_error_message("Build process failed.", status_code=HTTPStatus.INTERNAL_SERVER_ERROR)
    
    return res_builder.build_response_message("Build process initiated successfully.", status_code=HTTPStatus.OK)

@app.route('/system/api/v1/build/cleanup', methods=['POST'])    
def clean():
    """
    Cleanup Endpoint
    ---
    summary: Clean up old build jobs for the authenticated user.
    description: >
        This endpoint deletes build jobs older than a specified number of hours for the authenticated user.
        The user must provide a valid JSON payload with the optional parameter `max_age_hours` to specify the age threshold.
        If not provided, the default is 24 hours.
    tags:
      - Build
    security:
        - openwhiskBasicAuth: []
    consumes:
        - application/json
    operationId: cleanUpJobs
    parameters:
      - in: body
        name: BuildRequest
        required: true
        schema:
          type: object
          properties:
            max_age_hours:
                type: integer
                description: Maximum age of build jobs (in hours) to be deleted.
                default: 24
              
    responses:
      '200':
        description: Successfully cleaned up old build jobs.
        content:
          application/json:
            schema:
              type: object
              properties:
                message:
                  type: string
                  example: Cleaned up 5 jobs successfully.
      '400':
        description: Bad request. No JSON payload provided for cleanup.
        content:
          application/json:
            schema:
              type: object
              properties:
                error:
                  type: string
                  example: No JSON payload provided for cleanup.
      '401':
        description: Unauthorized. User environment not found.
        content:
          application/json:
            schema:
              type: object
              properties:
                error:
                  type: string
                  example: User environment not found
      '500':
        description: Internal server error. Failed to clean up old build jobs.
        content:
          application/json:
            schema:
              type: object
              properties:
                error:
                  type: string
                  example: Failed to clean up old build jobs.
    """

    auth_result = authorize()
    if isinstance(auth_result, Response):
      return auth_result
    
    env = env_to_dict(auth_result)
    if env is None:
        return res_builder.build_error_message("User environment not found", status_code=HTTPStatus.UNAUTHORIZED)
    
    if (request.json is None):
         return res_builder.build_error_message("No JSON payload provided for cleanup.", status_code=HTTPStatus.BAD_REQUEST)
    
    wsk_user_name = auth_result.get('login','').lower()
    env['wsk_user_name'] = wsk_user_name
    json_data = request.json
    max_age_hours = int(json_data.get('max_age_hours', 24)) 
    
    build_service = BuildService(user_env=env)
    clean_result = build_service.delete_old_build_jobs(max_age_hours=max_age_hours)
    if clean_result == -1:
        return res_builder.build_error_message("Failed to clean up old build jobs.", status_code=HTTPStatus.INTERNAL_SERVER_ERROR)
    
    return res_builder.build_response_message(f"Cleaned up {clean_result} jobs successfully.", status_code=HTTPStatus.OK)