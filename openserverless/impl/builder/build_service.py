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
import time
from openserverless.common.kube_api_client import KubeApiClient
import os
import uuid
import logging
from datetime import datetime, timezone, timedelta
from types import SimpleNamespace
import random
import string

JOB_NAME = "build"
CM_NAME = "cm"

class BuildService:
    """
    BuildService is responsible for managing the build process in a Kubernetes environment.
    It handles the creation of Dockerfiles, ConfigMaps, and Kubernetes Jobs to build Docker images
    based on the provided build configuration.
    """

    def __init__(self, user_env=None):
        # A super userful Kube Api Client
        self.kube_client = KubeApiClient()       
        
        # generate a unique ID for the build
        self.id = str(uuid.uuid4())

        # user environment variables
        self.user_env = user_env if user_env is not None else {}

        self.user = self.user_env.get('wsk_user_name', '')

        # define a unique ConfigMap and Job name based on the ID
        if len(self.user) > 0:
            self.cm = f"{CM_NAME}-{self.user}-{self.id}"
            self.job_name = f"{JOB_NAME}-{self.user}-{self.id}"
        else:
            self.cm = f"{CM_NAME}-{self.id}"
            self.job_name = f"{JOB_NAME}-{self.id}"
        
        # define registry host
        self.registry_host = self.get_registry_host()
        logging.info(f"Using registry host: {self.registry_host}")

        # define registry auth
        self.registry_auth = self.get_registry_auth()
        self.custom_registry_auth = False
        logging.info(f"Using registry auth: {self.registry_auth}")
    
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

    def get_registry_host(self) -> str:
        """
        Retrieve the registry host 
        - firstly, check if the user environment has a registry host set
        - otherwise retrieve the OpenServerless config map 
        - if not present use a default value
        """        
        # if customized by the user
        if (self.user_env.get('REGISTRY_HOST') is not None):
            return self.user_env.get('REGISTRY_HOST')

        # the default                
        registry_host = 'nuvolaris-registry-svc:5000'
        ops_config_map = self.kube_client.get_config_map('config')
        if ops_config_map is not None:
            if 'annotations' in ops_config_map.get('metadata', {}):
                annotations = ops_config_map['metadata']['annotations']
                if 'registry_host' in annotations:
                    registry_host = annotations['registry_host']
        
        return registry_host
    
    def get_registry_auth(self) -> str:
        """
        Get the name of the registry auth secret. If the user environment has a registry auth set, use it.        
        """
        if (self.user_env.get('REGISTRY_SECRET') is not None):
            custom_credentials = self.user_env.get('REGISTRY_SECRET')
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

            return self.user_env.get('REGISTRY_SECRET')
        
        return 'registry-pull-secret-int'

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

    def build(self, image_name: str) -> str:
        """ 
        Build the Docker image using the provided build configuration.
        The build configuration should include the source, target, and kind.
        """
        import tempfile
        import base64

        # define registry host
        self.registry_host = self.get_registry_host()
        if self.registry_host is None:
            return None
        logging.info(f"Using registry host: {self.registry_host}")

        # define registry auth
        self.registry_auth = self.get_registry_auth()

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
                requirements = base64.b64decode(self.build_config.get('file')).decode('utf-8')
                requirements_file = self.get_requirements_file_from_kind()
                
                with open(os.path.join(tmpdirname,requirements_file), 'w') as f:
                    f.write(requirements)
                
            except Exception as e:
                logging.error(f"Failed to decode the requirements file: {e}")
                return None    
        
        dockerfile_path = os.path.join(tmpdirname, "Dockerfile")
        logging.info(f"Creating Dockerfile at: {dockerfile_path}")
        with open(dockerfile_path, "w") as dockerfile:
            dockerfile.write(self.create_docker_file(requirements=requirements_file))
        
        # check if the directory contains a Dockerfile and is not empty.
        if not self.check_build_dir(tmpdirname):
            return None

        # Create a ConfigMap for the build context
        logging.info(f"Creating ConfigMap {self.cm} with build context")
        cm = self.kube_client.post_config_map(
            cm_name=self.cm,
            file_or_dir=tmpdirname,
        )

        logging.info(f"Removing temporary build directory: {tmpdirname}")
        shutil.rmtree(tmpdirname)

        if not cm:
            return None

        logging.info(f"ConfigMap {self.cm} created successfully")
        job_template = self.create_build_job(image_name)
        job = self.kube_client.post_job(job_template)
        if not job:
            logging.error(f"Failed to create job {self.job_name}")
            return None
        
        time.sleep(3)
        if not self.kube_client.delete_config_map(cm_name=self.cm):
            logging.error(f"Failed to delete ConfigMap {self.cm}")


        if self.custom_registry_auth:
            if not self.kube_client.delete_secret(secret_name=self.registry_auth):
                logging.error(f"Failed to delete Secret {self.custom_registry_auth}")

        return job
    
    def delete_old_build_jobs(self, max_age_hours: int = 24) -> int:
        name_filter = f"build-{self.user}-" if self.user else "build"        
        jobs = self.kube_client.get_jobs(name_filter=name_filter)

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

        # --- MANIFEST DEL JOB ---
        job_manifest = {
            "apiVersion": "batch/v1",
            "kind": "Job",
            "metadata": {"name": self.job_name},
            "spec": {
                "backoffLimit": 0,
                "template": {
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
                                "image": "moby/buildkit:master-rootless",
                                "command": ["sh", "-c"],
                                "args": [
                                    "rootlesskit buildkitd --config /config/buildkitd.toml  & sleep 3 && "
                                    f"buildctl build --progress=plain --frontend=dockerfile.v0 --local context=/workspace --local dockerfile=/workspace --output=type=image,name={registry_image_name},push=true"
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
