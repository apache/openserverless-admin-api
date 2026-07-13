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
import base64
import binascii
import hashlib
import re
import time
from openserverless import app
from http import HTTPStatus
from flask import request, Response

import openserverless.common.response_builder as res_builder
from openserverless.common.utils import env_to_dict
from openserverless.error.api_error import AuthorizationError
from openserverless.impl.builder.build_service import BuildService
from openserverless.impl.builder.build_catalog import BuildCatalog, BuildCatalogError
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


BUILD_ID_PATTERN = re.compile(r"^[a-f0-9]{64}$")
NAMESPACE_PATTERN = re.compile(r"^[a-z0-9]+(?:[._-][a-z0-9]+)*$")
MAX_BUILD_FILE_BYTES = 512 * 1024


def authenticated_environment(auth_result: dict) -> tuple[dict, str]:
    env = env_to_dict(auth_result)
    user_env = env_to_dict(auth_result, "userenv")
    env.update(user_env)
    username = str(auth_result.get("login", "")).lower()
    env["wsk_user_name"] = username
    return env, username


def decode_build_file(encoded_file: str) -> bytes:
    if not isinstance(encoded_file, str) or not encoded_file:
        raise ValueError("Build file must be a non-empty base64 string")
    if len(encoded_file) > 750_000:
        raise ValueError("Build file is too large")
    try:
        decoded = base64.b64decode(encoded_file, validate=True)
        decoded.decode("utf-8")
    except (binascii.Error, UnicodeDecodeError) as exc:
        raise ValueError("Build file must be valid base64-encoded UTF-8 text") from exc
    if len(decoded) > MAX_BUILD_FILE_BYTES:
        raise ValueError("Decoded build file is too large")
    return decoded


def build_identity(builder_id: str, builder: dict, file_content: bytes) -> str:
    identity = hashlib.sha256()
    identity.update(b"openserverless-runtime-builder-v1\0")
    identity.update(builder_id.encode())
    identity.update(b"\0")
    identity.update(builder["kind"].encode())
    identity.update(b"\0")
    identity.update(builder["source"].encode())
    identity.update(b"\0")
    identity.update(file_content)
    return identity.hexdigest()


@app.route('/system/api/v1/build/capabilities', methods=['GET'])
def build_capabilities():
    auth_result = authorize()
    if isinstance(auth_result, Response):
        return auth_result
    try:
        catalog = BuildCatalog()
    except BuildCatalogError as exc:
        return res_builder.build_error_message(str(exc), HTTPStatus.INTERNAL_SERVER_ERROR)
    return res_builder.build_response_message(
        "Builder capabilities retrieved", {"builders": catalog.capabilities()}
    )


@app.route('/system/api/v1/build/ensure', methods=['POST'])
def ensure_build():
    """Ensure a content-addressed custom runtime image exists."""
    auth_result = authorize()
    if isinstance(auth_result, Response):
        return auth_result
    if request.json is None:
        return res_builder.build_error_message("No JSON payload provided", HTTPStatus.BAD_REQUEST)

    try:
        catalog = BuildCatalog()
        builder_id = request.json.get("builder", "")
        builder = catalog.get(builder_id)
        encoded_file = request.json.get("file", "")
        file_content = decode_build_file(encoded_file)
    except (BuildCatalogError, ValueError) as exc:
        return res_builder.build_error_message(str(exc), HTTPStatus.BAD_REQUEST)

    env, username = authenticated_environment(auth_result)
    if not username or not NAMESPACE_PATTERN.fullmatch(username):
        return res_builder.build_error_message("Authenticated namespace not found", HTTPStatus.UNAUTHORIZED)

    # The content-addressed endpoint always uses cluster-managed registry
    # settings. Do not inherit REGISTRY_HOST or REGISTRY_SECRET overrides from
    # a user environment.
    env = {"wsk_user_name": username}

    build_id = build_identity(builder_id, builder, file_content)
    image_name = f"{username}:{builder['kind']}-{build_id[:20]}"
    service = BuildService(user_env=env, build_id=build_id)
    current = service.get_build_status(image_name)
    if current is not None:
        if current["state"] == "failed" and request.json.get("retry", True):
            service._cleanup_build_resources()
            service.kube_client.delete_job(service.job_name)
            for _ in range(40):
                if service.kube_client.get_job(service.job_name) is None:
                    current = None
                    break
                time.sleep(0.25)
            if current is not None:
                return res_builder.build_error_message(
                    "Failed build cleanup is still in progress", HTTPStatus.CONFLICT
                )
        if current is None:
            pass
        else:
            status_code = HTTPStatus.OK if current["state"] == "succeeded" else HTTPStatus.ACCEPTED
            if current["state"] == "failed":
                status_code = HTTPStatus.CONFLICT
            return res_builder.build_response_message(current["message"], current, status_code)

    service.init(
        build_config={
            "source": builder["source"],
            "target": image_name,
            "kind": builder["kind"],
            "file": encoded_file,
        }
    )
    success, message = service.build(image_name)
    if not success:
        return res_builder.build_error_message(message, HTTPStatus.INTERNAL_SERVER_ERROR)

    return res_builder.build_response_message(
        "Build queued",
        {
            "id": build_id,
            "job_name": service.job_name,
            "state": "queued",
            "image": None,
        },
        HTTPStatus.ACCEPTED,
    )


@app.route('/system/api/v1/build/<build_id>', methods=['GET'])
def build_status(build_id):
    auth_result = authorize()
    if isinstance(auth_result, Response):
        return auth_result
    if not BUILD_ID_PATTERN.fullmatch(build_id):
        return res_builder.build_error_message("Invalid build id", HTTPStatus.BAD_REQUEST)

    env, username = authenticated_environment(auth_result)
    if not username or not NAMESPACE_PATTERN.fullmatch(username):
        return res_builder.build_error_message("Authenticated namespace not found", HTTPStatus.UNAUTHORIZED)
    env = {"wsk_user_name": username}
    service = BuildService(user_env=env, build_id=build_id)
    current = service.get_build_status()
    if current is None:
        return res_builder.build_error_message("Build not found", HTTPStatus.NOT_FOUND)
    if current["state"] in ("succeeded", "failed"):
        service._cleanup_build_resources()
    status_code = HTTPStatus.OK
    if current["state"] in ("queued", "running"):
        status_code = HTTPStatus.ACCEPTED
    elif current["state"] == "failed":
        status_code = HTTPStatus.CONFLICT
    return res_builder.build_response_message(current["message"], current, status_code)

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
          required:
            - source
            - target
            - kind
          properties:
            source:
              type: string
              description: Source image for the build (e.g., ghcr.io/nuvolaris/openserverless-runtime-python:3.12)
              example: "ghcr.io/nuvolaris/openserverless-runtime-python:3.12"
            target:
              type: string
              description: Target image name in format username:tag (must match authenticated user)
              example: "myuser:custom-tag"
            kind:
              type: string
              description: Runtime kind (python, nodejs, java, php, go, ruby, dotnet)
              enum: [python, nodejs, java, php, go, ruby, dotnet]
              example: "python"
            file:
              type: string
              description: Base64-encoded requirements file (optional, e.g., requirements.txt for Python)
              example: "cmVxdWVzdHM9PTIuMzEuMA=="
    responses:
      200:
        description: Build process initiated successfully.
        schema:
          type: object
          properties:
            message:
              type: string
              example: "Build process initiated successfully. Job: build-myuser-abc123"
            data:
              type: object
              properties:
                id:
                  type: string
                  description: Unique build ID
                  example: "550e8400-e29b-41d4-a716-446655440000"
                job_name:
                  type: string
                  description: Kubernetes job name
                  example: "build-myuser-abc123"
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
    user_env = env_to_dict(auth_result,"userenv")
    for key in user_env:
        env[key]=user_env[key]

    # Check if env is empty (env_to_dict returns dict, never None)
    if not env:
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

    # Strict user check is enabled by default for security
    strict_user_check = os.environ.get("STRICT_USER_CHECK", "true").lower() not in ("false", "0", "no", "off")
    if strict_user_check and (wsk_user_name != target_user):
        return res_builder.build_error_message("Invalid target for the build.", status_code=HTTPStatus.BAD_REQUEST)

    env['wsk_user_name'] = wsk_user_name
    build_service = BuildService(user_env=env)
    build_service.init(build_config=json_data)
    success, msg = build_service.build(json_data.get('target')) 

    if not success:
      return res_builder.build_error_message(msg or "Build process failed.", status_code=HTTPStatus.INTERNAL_SERVER_ERROR)

    additional_data = {"id": build_service.id, "job_name": build_service.job_name }
    return res_builder.build_response_message(f"Build process initiated successfully. Job: {msg}", 
                                              data=additional_data,
                                              status_code=HTTPStatus.OK)

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
      200:
        description: Successfully cleaned up old build jobs.
        schema:
          type: object
          properties:
            message:
              type: string
              example: "Cleaned up 5 jobs successfully."
      400:
        description: Bad request. No JSON payload provided for cleanup.
        schema:
          type: object
          properties:
            error:
              type: string
              example: "No JSON payload provided for cleanup."
      401:
        description: Unauthorized. User environment not found.
        schema:
          type: object
          properties:
            error:
              type: string
              example: "User environment not found"
      500:
        description: Internal server error. Failed to clean up old build jobs.
        schema:
          type: object
          properties:
            error:
              type: string
              example: "Failed to clean up old build jobs."
    """

    auth_result = authorize()
    if isinstance(auth_result, Response):
      return auth_result

    env = env_to_dict(auth_result)
    # Check if env is empty (env_to_dict returns dict, never None)
    if not env:
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
