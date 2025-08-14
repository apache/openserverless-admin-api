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
# Deployer

These tasks are useful to interact with OpenServerless Admin Api Builder

There are some tasks to interact with OpenServerless internal registry too.

## Available tasks

task: Available tasks for this project:

```
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

### List images for the user

`task builder:list-images CATALOG=devel`

### Delete an image for the user

`task builder:delete-image IMAGE=devel:alpine`

# Useful Links

- https://crazymax.dev/buildkit/user-guides/rootless-mode/
- https://www.linkedin.com/pulse/kubernetes-v133-user-namespaces-revolutionizing-false-rodrigo-mqoif/
- https://chatgpt.com/c/689c9b5b-1d3c-8333-9f25-19d016fdacd0
- https://kubernetes.io/docs/concepts/workloads/pods/user-namespaces/