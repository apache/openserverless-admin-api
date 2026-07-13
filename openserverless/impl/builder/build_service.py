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
import shutil
from openserverless.common.kube_api_client import KubeApiClient
import os
import uuid
import logging
import re
import shlex
from datetime import datetime, timezone, timedelta
from types import SimpleNamespace
import random
import string
import binascii

JOB_NAME = "build"
CM_NAME = "cm"

class BuildService:
    """
    BuildService is responsible for managing the build process in a Kubernetes environment.
    It handles the creation of Dockerfiles, ConfigMaps, and Kubernetes Jobs to build Docker images
    based on the provided build configuration.
    """

    def __init__(self, user_env=None, build_id=None, kube_client=None):
        # A super userful Kube Api Client
        self.kube_client = kube_client or KubeApiClient()
        
        # generate a unique ID for the build
        self.id = build_id or str(uuid.uuid4())

        # user environment variables
        self.user_env = user_env if user_env is not None else {}

        self.user = self.user_env.get('wsk_user_name', '')

        # Kubernetes names are deliberately derived from the authenticated
        # namespace and the build id. This makes build creation idempotent and
        # prevents a client supplied image name from reaching a shell command.
        safe_user = re.sub(r"[^a-z0-9-]", "-", self.user.lower()).strip("-")
        safe_user = (safe_user or "user")[:24]
        safe_id = re.sub(r"[^a-z0-9-]", "", self.id.lower())[:20]
        if len(self.user) > 0:
            self.cm = f"{CM_NAME}-{safe_user}-{safe_id}"
            self.job_name = f"{JOB_NAME}-{safe_user}-{safe_id}"
        else:
            self.cm = f"{CM_NAME}-{safe_id}"
            self.job_name = f"{JOB_NAME}-{safe_id}"
        
        # define registry host
        self.registry_host = self.get_registry_push_host()
        logging.info(f"Using registry host: {self.registry_host}")

        # define registry auth
        #self.registry_auth = self.get_registry_auth()
        self.custom_registry_auth = False
        #logging.info(f"Using registry auth: {self.registry_auth}")
    
    def init(self, build_config: dict):
        """
        Initialize the build service by creating the necessary ConfigMap.
        """
        logging.info("Initializing BuildService")
        
        self.build_config = build_config

        # install the nuvolaris-buildkitd-conf ConfigMap if not present
        cm = self.kube_client.get_config_map("nuvolaris-buildkitd-conf")
        if cm is None:
            logging.info("Adding nuvolaris-buildkitd-conf ConfigMap")
            status = self.kube_client.post_config_map(
                cm_name="nuvolaris-buildkitd-conf",
                file_or_dir="deploy/buildkit/buildkitd.toml",
                namespace="nuvolaris",
            )
            if status is None:
                logging.error("Failed to create nuvolaris-buildkitd-conf ConfigMap")

    def create_registry_secret(self, username: str, password: str, registry: str):
        randompart = ''.join(random.choices(string.ascii_lowercase + string.digits, k=5))
        random_name = f"reg-{self.user}-{randompart}"
        conf = KubeApiClient.build_dockerconfigjson(username=username, password=password,registry=registry)

        data = {".dockerconfigjson": conf}
        secret = self.kube_client.post_secret(secret_name=random_name, secret_data=data, type="kubernetes.io/dockerconfigjson")
        return secret

    def _get_registry_annotation(self, name: str, default: str = "") -> str:
        ops_config_map = self.kube_client.get_config_map('config')
        if ops_config_map is None:
            return default
        annotations = ops_config_map.get('metadata', {}).get('annotations', {})
        return str(annotations.get(name, default)).strip()

    def get_registry_push_host(self) -> str:
        """
        Return the endpoint used by BuildKit pods to push an image.

        This is intentionally separate from the host embedded in an action
        image reference: a Kubernetes Service is reachable by BuildKit, but it
        is generally not resolvable by containerd on a cluster node.
        """
        registry_host = os.environ.get("REGISTRY_PUSH_HOST", "").strip()
        if registry_host:
            return registry_host
        user_registry_host = self.user_env.get('REGISTRY_PUSH_HOST', "").strip()
        if user_registry_host:
            return user_registry_host
        return (
            self._get_registry_annotation("registry_push_host")
            or self._get_registry_annotation("registry_internal_host")
            or "nuvolaris-registry-svc:5000"
        )

    def get_registry_pull_host(self) -> str:
        """Return the registry host that cluster nodes use for action pulls."""
        registry_host = os.environ.get("REGISTRY_PULL_HOST", "").strip()
        if registry_host:
            return registry_host
        user_registry_host = self.user_env.get('REGISTRY_PULL_HOST', "").strip()
        if user_registry_host:
            return user_registry_host
        return (
            self._get_registry_annotation("registry_pull_host")
            or self._get_registry_annotation("registry_host")
            or self.get_registry_push_host()
        )

    # Kept for callers of the alpha builder API. New code must use the
    # explicit push/pull methods above.
    def get_registry_host(self) -> str:
        return self.get_registry_push_host()
    
    def get_registry_auth(self) -> str:
        """
        Get the name of the registry auth secret. If the user environment has a registry auth set, use it.        
        """
        if (self.user_env.get('REGISTRY_SECRET') is not None):
            custom_credentials = self.user_env.get('REGISTRY_SECRET',"")
            # if not ':' it means that the user is referencing an already created custom secret
            if ":" not in custom_credentials:
                return custom_credentials
        
            username, password = custom_credentials.split(":")
            registry_secret = self.create_registry_secret(
                username=username, password=password,
                registry=self.registry_host
            )
            if registry_secret is not None:
                self.registry_auth = registry_secret['metadata']['name']
                # is custom only when is not equal to the default
                if self.registry_auth != "registry-pull-secret":
                    self.custom_registry_auth = True
                return self.registry_auth
            else:
                logging.error(f"Failed to create registry secret for custom credentials")
                
        
        return os.environ.get("REGISTRY_PUSH_SECRET", "registry-pull-secret-int")

    def create_docker_file(self, requirements=None) -> str:
        """
        Create a Dockerfile in the current directory.
        """
        source = self.build_config.get("source")
        
        dockerfile_content = f"FROM {source}\n\n"
        
        if 'file' in self.build_config:            
            if requirements is not None:
                dockerfile_content += f"COPY {requirements} /tmp/{requirements}\n"                
                dockerfile_content += "USER root\n"
                dockerfile_content += "RUN /bin/extend\n"
                dockerfile_content += "USER nobody\n"
            

        return dockerfile_content
    
    def get_requirements_file_from_kind(self) -> str:
        """
        Get the requirements file based on the kind of the build.
        """
        kind = self.build_config.get("kind")
        if kind == 'python':
            return 'requirements.txt'
        elif kind == 'nodejs':
            return 'package.json'
        elif kind == 'php':
            return 'composer.json'
        elif kind == 'java':
            return 'pom.xml'
        elif kind == 'go':
            return 'go.mod'
        elif kind == 'ruby':
            return 'Gemfile'
        elif kind == 'dotnet':
            return 'project.json'
        else:
            raise ValueError(f"Unsupported kind: {kind}")

    def build(self, image_name: str) -> tuple[bool, str]:
        """
        Build the Docker image using the provided build configuration.
        The build configuration should include the source, target, and kind.

        Returns:
            tuple[bool, str]: (success, message). On success `success` is True
            and `message` contains the created job name. On failure `success`
            is False and `message` contains an error description.
        """
        import tempfile
        import base64

        # define registry host
        self.registry_host = self.get_registry_host()
        if self.registry_host is None:
            return (False, "No registry host configured")
        logging.info(f"Using registry host: {self.registry_host}")

        # define registry auth
        self.registry_auth = self.get_registry_auth()

        secret = self.kube_client.get_secret(self.registry_auth)
        if secret is None:
            return (False, f"Secret {self.registry_auth} is not configured!")

        logging.info(f"Using registry auth: {self.registry_auth}")

        # firstly remove old build jobs
        self.delete_old_build_jobs()

        tmpdirname = tempfile.mkdtemp()
        logging.info(f"Starting the build to: {tmpdirname}")
        requirements_file = None
        if 'file' in self.build_config:
            logging.info("Decoding the requirements file from base64")
            # decode base64 self.build_config.get('file')
            try:
                file_data = self.build_config.get('file', "")

                # Validate base64 data size (10MB limit for encoded data)
                if len(file_data) > 10_000_000:
                    return (False, "Requirements file too large (max 10MB base64-encoded)")

                # Decode base64 and UTF-8
                requirements = base64.b64decode(file_data).decode('utf-8')

                # Validate decoded size (5MB limit for decoded text)
                if len(requirements) > 5_000_000:
                    return (False, "Decoded requirements file too large (max 5MB)")

                requirements_file = self.get_requirements_file_from_kind()

                with open(os.path.join(tmpdirname, requirements_file), 'w') as f:
                    f.write(requirements)

            except binascii.Error as e:
                logging.error(f"Invalid base64 encoding: {e}")
                return (False, "Requirements file must be valid base64-encoded data")
            except UnicodeDecodeError as e:
                logging.error(f"Invalid UTF-8 encoding: {e}")
                return (False, "Requirements file must be valid UTF-8 text")
            except IOError as e:
                logging.error(f"Failed to write requirements file: {e}")
                return (False, f"Failed to write requirements file: {e}")
        
        dockerfile_path = os.path.join(tmpdirname, "Dockerfile")
        logging.info(f"Creating Dockerfile at: {dockerfile_path}")
        with open(dockerfile_path, "w") as dockerfile:
            dockerfile.write(self.create_docker_file(requirements=requirements_file))
        
        # check if the directory contains a Dockerfile and is not empty.
        if not self.check_build_dir(tmpdirname):
            return (False, "Build directory invalid or missing Dockerfile")

        # Create a ConfigMap for the build context
        logging.info(f"Creating ConfigMap {self.cm} with build context")
        cm = self.kube_client.post_config_map(
            cm_name=self.cm,
            file_or_dir=tmpdirname,
        )

        logging.info(f"Removing temporary build directory: {tmpdirname}")
        shutil.rmtree(tmpdirname)

        if not cm:
            return (False, "Failed to create ConfigMap for build context")

        logging.info(f"ConfigMap {self.cm} created successfully")
        try:
            job_template = self.create_build_job(image_name)
        except ValueError as exc:
            self._cleanup_build_resources()
            return (False, str(exc))

        job = self.kube_client.post_job(job_template)
        if not job:
            logging.error(f"Failed to create job {self.job_name}")
            # Cleanup resources if job creation failed
            self._cleanup_build_resources()
            return (False, f"Failed to create job {self.job_name}")

        logging.info(f"Job {self.job_name} created successfully")

        # Do not wait for the Job in the HTTP start request. The client polls the
        # status endpoint and cleanup is performed after a terminal condition.
        return (True, self.job_name)

    def action_image(self, image_name: str) -> str:
        """Return the image reference that must be stored on an action."""
        return f"{self.get_registry_pull_host()}/{image_name}"

    def get_build_status(self, image_name: str | None = None) -> dict | None:
        """Return a stable state for the deterministic build Job."""
        job = self.kube_client.get_job(self.job_name)
        if job is None:
            return None

        if image_name is None:
            image_name = (
                job.get("metadata", {})
                .get("annotations", {})
                .get("openserverless.apache.org/target-image")
            )

        status = job.get("status", {})
        conditions = status.get("conditions") or []
        state = "queued"
        message = "Build is queued"
        for condition in conditions:
            if condition.get("type") == "Complete" and condition.get("status") == "True":
                state = "succeeded"
                message = condition.get("message") or "Build completed"
                break
            if condition.get("type") == "Failed" and condition.get("status") == "True":
                state = "failed"
                message = condition.get("message") or condition.get("reason") or "Build failed"
                break
        else:
            if status.get("active", 0) > 0:
                state = "running"
                message = "Build is running"

        return {
            "id": self.id,
            "job_name": self.job_name,
            "state": state,
            "message": message,
            "image": self.action_image(image_name) if state == "succeeded" and image_name else None,
        }
    
    def _cleanup_build_resources(self):
        """
        Clean up temporary resources (ConfigMap and custom registry Secret) created for the build.
        This should only be called after the init container has completed copying the build context.
        """
        # Cleanup ConfigMap - safe to delete after init container copies it
        if not self.kube_client.delete_config_map(cm_name=self.cm):
            logging.error(f"Failed to delete ConfigMap {self.cm}")
        else:
            logging.info(f"Successfully deleted ConfigMap {self.cm}")

        # Cleanup custom registry secret if one was created
        if self.custom_registry_auth:
            if not self.kube_client.delete_secret(secret_name=self.registry_auth):
                logging.error(f"Failed to delete Secret {self.registry_auth}")
            else:
                logging.info(f"Successfully deleted Secret {self.registry_auth}")

    def delete_old_build_jobs(self, max_age_hours: int = 24) -> int:
        name_filter = f"build-{self.user}-" if self.user else "build"
        jobs = self.kube_client.get_jobs(name_filter=name_filter)

        if jobs is None:
            logging.error("Failed to retrieve jobs list")
            return -1

        try:
            cutoff_time = datetime.now(timezone.utc) - timedelta(hours=max_age_hours)
            count = 0

            for j in jobs:
                job = SimpleNamespace(**j)
                metadata = SimpleNamespace(**job.metadata)
                status = SimpleNamespace(**job.status)
                
                if not metadata or not status:
                    continue

                job_name = metadata.name

                completed = False
                # Check if job is completed
                for c in status.conditions:
                    condition = SimpleNamespace(**c)
                    if condition.type == "Complete" and condition.status == "True":
                        completed = True
                        break

                if not completed:
                    continue

                # Check completion time
                completion_time = status.completionTime
                if not completion_time:
                    continue
                job_completion_time = datetime.strptime(completion_time,"%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=timezone.utc)

                if job_completion_time < cutoff_time:
                    logging.info (f"Deleting job {job_name} (completed at {completion_time})")
                    status = self.kube_client.delete_job(job_name=job_name)
                    if not status:
                        logging.error(f"Failed to delete job {job_name}")
                    else:
                        count+=1
                        logging.info(f"Job {job_name} deleted successfully")
            
            return count
        except Exception as e:
            logging.error(f"Error deleting old build jobs: {e}")
            return -1

    
    def check_build_dir(self, unzip_dir: str) -> bool:
        """
        Check if the unzipped directory contains a Dockerfile and is not empty."""
        if not os.path.exists(unzip_dir):
            return False

        # Check if the directory contains a Dockerfile
        dockerfile_path = os.path.join(unzip_dir, "Dockerfile")
        if not os.path.exists(dockerfile_path):
            return False

        return True

    def create_build_job(self, image_name: str) -> dict:
        """Create a Kubernetes job manifest for building the Docker image."""
        if not self.custom_registry_auth:
            registry_image_name = f"{self.registry_host}/{image_name}"
        else:
            registry_image_name = f"{image_name}"

        if "://" in registry_image_name or not re.fullmatch(
            r"[A-Za-z0-9][A-Za-z0-9._:/@-]{0,511}", registry_image_name
        ):
            raise ValueError("Invalid target image reference")
        quoted_registry_image_name = shlex.quote(registry_image_name)

        # --- MANIFEST DEL JOB ---
        job_manifest = {
            "apiVersion": "batch/v1",
            "kind": "Job",
            "metadata": {
                "name": self.job_name,
                "labels": {
                    "openserverless.apache.org/component": "runtime-builder",
                    "openserverless.apache.org/build-id": self.id[:63],
                },
                "annotations": {
                    "openserverless.apache.org/target-image": image_name,
                },
            },
            "spec": {
                "backoffLimit": 0,
                "template": {
                    "metadata": {
                        "labels": {
                            "openserverless.apache.org/component": "runtime-builder",
                            "openserverless.apache.org/build-id": self.id[:63],
                        }
                    },
                    "spec": {
                        "restartPolicy": "Never",
                        "volumes": [
                            {
                                "name": "nuvolaris-buildkitd-conf",
                                "configMap": {"name": "nuvolaris-buildkitd-conf"},
                            },
                            {
                                "name": "build-context-vol",
                                "configMap": {"name": self.cm},
                            },
                            {"name": "workspace", "emptyDir": {}},
                            {"name": "img-cache", "emptyDir": {}},
                            {"name": "cdi-etc", "emptyDir": {}},
                            {"name": "cdi-run", "emptyDir": {}},
                            {"name": "cdi-buildkit", "emptyDir": {}},
                            {
                                "name": "docker-config",
                                "secret": {
                                    "secretName": self.registry_auth,
                                    "items": [
                                        {
                                            "key": ".dockerconfigjson",
                                            "path": "config.json",
                                        }
                                    ],
                                },
                            },
                        ],
                        "initContainers": [
                            {
                                "name": "copy-build-context",
                                "image": "busybox:1.36",
                                "command": [
                                    "sh", "-c", "cp -rvL /configmap/* /workspace/ && cat /workspace/Dockerfile",
                                ],
                                "volumeMounts": [
                                    { "name": "build-context-vol", "mountPath": "/configmap", },
                                    { "name": "workspace", "mountPath": "/workspace" },
                                ],
                            }
                        ],
                        "containers": [
                            {
                                "name": "buildkit",
                                "image": os.environ.get(
                                    "BUILDKIT_IMAGE", "moby/buildkit:v0.30.0-rootless"
                                ),
                                "command": ["sh", "-c"],
                                "args": [
                                    "rootlesskit buildkitd --config /config/buildkitd.toml  & sleep 3 && "
                                    f"buildctl build --progress=plain --frontend=dockerfile.v0 --local context=/workspace --local dockerfile=/workspace --output=type=image,name={quoted_registry_image_name},push=true"
                                ],                                
                                "securityContext": {
                                    "runAsUser": 1000,
                                    "runAsGroup": 1000,
                                    "allowPrivilegeEscalation": True,
                                    "privileged": True,
                                    "seccompProfile": { "type": "Unconfined" }
                                },
                                "env": [
                                    { "name": "BUILDKIT_ROOTLESS", "value": "1" }
                                ],
                                "volumeMounts": [
                                    { "name": "nuvolaris-buildkitd-conf", "mountPath": "/config" },
                                    { "name": "workspace", "mountPath": "/workspace" },
                                    { "name": "docker-config", "mountPath": "/home/user/.docker" },
                                    { "name": "img-cache", "mountPath": "/tmp" },
                                    { "name": "cdi-etc", "mountPath": "/etc/cdi" },
                                    { "name": "cdi-run", "mountPath": "/var/run/cdi" },
                                    { "name": "cdi-buildkit", "mountPath": "/etc/buildkit/cdi" },
                                ],
                            }
                        ],
                    }
                },
            },
        }

        return job_manifest
