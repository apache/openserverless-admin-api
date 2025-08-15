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
# OpenServerless Admin API

## Project description

Lighweight OpenServerless Admin REST API Layer.


## Endpoints

Available APIs at the moment:

### Authentication API

`POST /system/api/v1/auth` - Perform the user Authentication relying on wsku metadata stored into internal CouchDB.

`PATCH /system/api/v1/auth/{login}` - Update the user password patching the corresponding wsku/\<login\> entry.

### Build API

`POST /system/api/v1/build` - Perform the build of a custom image and push it to repository.

More informations [Here](docs/DEPLOYER.md)

### Info API

`GET /system/info` - Info endpoint

## Developer instructions

You need to have access to be Apache OpenServerless admin and have access to kubernetes cluster.

Refer to the [Apache OpenServerless installation page](https://openserverless.apache.org/docs/installation/install/docker/): 

Give the command `task dev:setup-developer` and it will:

- extract the required ca.crt and token from operator service account
- copy a sample .env file
- install required python dependencies

After that, you can use VSCode debugger to start the application.
Otherwise you can give an `uv run -m openserverless` to start.

Open http://localhost:5002/system/apidocs/ to see the API documentation.

## Tasks

Taskfile supports the following tasks:

```yaml
* build:                       Build the image locally
* build-and-load:              Build the image and loads it to local Kind cluster
* buildx:                      Build the docker image using buildx. Set PUSH=1 to push the image to the registry. 
* docker-login:                Login to the docker registry. Set REGISTRY=ghcr or REGISTRY=dockerhub in .env to use the respective registry. 
* image-tag:                   Create a new tag for the current git commit.       
* builder:cleanjobs:           Clean up old jobs
* builder:delete-image:        Delete an image from the registry
* builder:get-image:           Get an image from the registry
* builder:list-catalogs:       List catalogs in the registry
* builder:list-images:         List images in a specific catalog
* builder:logs:                Show logs of the last build job
* builder:send:                Send the build to the server
* builder:updatetoml:          Update the buildkitd.toml file config map
* dev:get-tokens:              Get Service Account tokens and save them to tokens directory
* dev:run:                     Run the admin api locally, using configuration from .env file 
* dev:setup-developer:         Setup developer environment
```

## Build and push

### Private registry or local image

To build an image and push it on a private repository, firstly choose which
registry you want to use.
Tasks support is for Github (ghcr) and Dockerhub (dockerhub).
So copy the `.env.example` to `.env` and configure the required variables for
authentication and set the `REGISTRY` and `NAMESPACE` accordly.

Now create a new tag

```bash
$ task image-tag
```
You should see an output like this:

```bash
Deleted tag '0.1.0-incubating.2507270903' (was 434b400)
0.1.0-incubating.2507270910
```

:bulb: **NOTE** If you leave unset `REGISTRY` a local `openserverless-admin-api` 
image will be built, using the generated tag.

If you setup the `REGISTRY` and `NAMESPACE`, you can give a:

```bash
$ task docker-login
```

To build:

```bash
$ task buildx
```

To build and push

```bash
$ task buildx PUSH=1
```

### Apache repository
To build an official Apache OpenServerless Admin Api image, you
need to be a committer.

If you have the proper permissions, the build process will start pushing a
new tag to apache/openserverless-admin-api repository.
So, for example,  if your tag is `0.1.0-incubating.2507270910` and your
git remote is `apache`

```bash
$ git push apache 0.1.0-incubating.2507270910
```

This will trigger the build workflow, and the process will be visible at
https://github.com/apache/openserverless-admin-api/actions

## Additional Documentation

- [Deployer](docs/DEPLOYER.md)