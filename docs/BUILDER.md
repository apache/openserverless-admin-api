<!--
  ~ Licensed to the Apache Software Foundation (ASF) under one
  ~ or more contributor license agreements.  See the NOTICE file
  ~ distributed with this work for additional information
  ~ regarding copyright ownership.  The ASF licenses this file
  ~ to you under the Apache License, Version 2.0 (the
  ~ "License"); you may not use this file except in compliance
  ~ with the License.  You may obtain a copy of the License at
  ~
  ~   http://www.apache.org/licenses/LICENSE-2.0
  ~
  ~ Unless required by applicable law or agreed to in writing,
  ~ software distributed under the License is distributed on an
  ~ "AS IS" BASIS, WITHOUT WARRANTIES OR CONDITIONS OF ANY
  ~ KIND, either express or implied.  See the License for the
  ~ specific language governing permissions and limitations
  ~ under the License.
  ~
-->
# Builder

Builder is the implementation of the feature described 
in [OpenServerless Issue 156](https://github.com/apache/openserverless/issues/156).

Specifically, the builder can extend a default runtime with user-defined 
"requirements" by generating a new "extended" user runtime and pushing it to 
OpenServerless’ internal Docker registry.

Actually, the supported "requirements" are listed in the following table:

|  kind  | requirement file |
|:-------|:-----------------|
| go     | go.mod           |
| java   | pom.xml          |
| nodejs | package.json     |
| php    | composer.json    |
| python | requirements.txt |
| ruby   | Gemfile          |
| dotnet | project.json     |

*NOTE*: this list will be improved when new extendible runtimes will be ready.

The "requirement" can be passed as base64 encoded string inside the `file` attribute
of the json body payload:

```json
{
  "source": "apache/openserverless-runtime-python:v3.13-2506091954", 
  "target": "devel:python3.12-custom", 
  "kind": "python", 
  "file": "Z25ld3MKYmVhdXRpZnVsc291cDQ="
}
```

By default the builder will push to OpenServerless internal docker registry.
To detect the host, it will use the `registry_host` inside the Operator's config 
map.
To authenticate, it will use the imagePullSecret named `registry-pull-secret` 
(these credentials are valid to push and pull from the internal registry).

The builder supports also pushing to an external private docker registry, using 
ops env:

- `REGISTRY_HOST` - put here the hostname:port of the external private registry.
- `REGISTRY_SECRET` - put here the name of a kubernetes secret containing an 
imagePullSecret able to push to the registry specified by `REGISTRY_HOST`.

This project has also support tasks:

- to test the build.
- to interact with OpenServerless internal registry too.

See [Examples](#examples) section

## Endpoints

`POST /system/api/v1/build/start` - Perform the build of a custom image and push it to repository.

`GET /system/api/v1/build/status` - Get the status of a build job by its id.

`POST /system/api/v1/build/cleanup` - Perform cleanup of build jobs older than 24 hours (or different number of hours if otherwise specified)

All endpoints require the wsk token in an `authorization` header.
The token will be used to check the user (the target image hash needs to be 
always in the format `user:image-tag`).

### Checking a build's status

`GET /system/api/v1/build/status?id=<build-id>` returns the current status of the
Kubernetes job created by `/build/start`, identified by the `id` returned in that
call's response.

Example response:

```json
{
  "message": "Build status retrieved successfully.",
  "data": {
    "id": "550e8400-e29b-41d4-a716-446655440000",
    "job_name": "build-myuser-abc123",
    "phase": "Succeeded",
    "active": 0,
    "succeeded": 1,
    "failed": 0,
    "startTime": "2026-08-22T10:00:00Z",
    "completionTime": "2026-08-22T10:02:30Z"
  }
}
```

`phase` is one of `Pending`, `Running`, `Succeeded`, or `Failed`. A `404` is
returned if no build job with the given id exists for the authenticated user.

## Available tasks

task: Available tasks for this project:

```
* builder:clean:               Cleanup old build jobs via api
* builder:cleanjobs:           Clean up old jobs
* builder:delete-image:        Delete an image from the registry
* builder:get-image:           Get an image from the registry
* builder:list-catalogs:       List catalogs in the registry
* builder:list-images:         List images in a specific catalog
* builder:logs:                Show logs of the last build job
* builder:send:                Send the build to the server
* builder:updatetoml:          Update the buildkitd.toml file config map
```

## Examples

### Build a custom runtime

`task builder:send SOURCE=apache/openserverless-runtime-python:v3.13-2506091954 TARGET=devel:python3.13-custom KIND=python REQUIREMENTS=$(base64 -i deploy/samples/requirements.txt)`

### Clenaup of old jobs via API

`task builder:clean MAX_AGE_HOURS=2`

MAX_AGE_HOURS, if not specified, has a default value of 24.

### List images for the user

`task builder:list-images CATALOG=devel`

### Delete an image for the user

`task builder:delete-image IMAGE=devel:alpine`

# Useful Links

- https://crazymax.dev/buildkit/user-guides/rootless-mode/
- https://www.linkedin.com/pulse/kubernetes-v133-user-namespaces-revolutionizing-false-rodrigo-mqoif/
- https://chatgpt.com/c/689c9b5b-1d3c-8333-9f25-19d016fdacd0
- https://kubernetes.io/docs/concepts/workloads/pods/user-namespaces/