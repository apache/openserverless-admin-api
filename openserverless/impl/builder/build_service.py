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

JOB_NAME = "build"
CM_NAME = "cm"


class BuildService:
    def __init__(self, build_config, user_env=None):
        self.build_config = build_config

        # A super userful Kube Api Client
        self.kube_client = KubeApiClient()
        
        # generate a unique ID for the build
        self.id = str(uuid.uuid4())

        # define a unique ConfigMap and Job name based on the ID
        self.cm = f"{CM_NAME}-{self.id}"
        self.job_name = f"{JOB_NAME}-{self.id}"

        # user environment variables
        self.user_env = user_env if user_env is not None else {}

        # define registry host
        self.registry_host = self.get_registry_host()

        self.init()
    
    def init(self):
        """
        Initialize the build service by creating the necessary ConfigMap.
        """

        # install the nuvolaris-buildkitd-conf ConfigMap if not present
        cm = self.kube_client.get_config_map("nuvolaris-buildkitd-conf", namespace="nuvolaris")
        if cm is None:
            self.kube_client.post_config_map(
                cm_name="nuvolaris-buildkitd-conf",
                file_or_dir="deploy/buildkit/buildkitd.toml",
                namespace="nuvolaris",
            )

    def get_registry_host(self):
        """
        Retrieve the registry host 
        - firstly, check if the user environment has a registry host set
        - otherwise retrieve the OpenServerless config map 
        - if not present use a default value
        """
        registry_host = 'nuvolaris-registry-svc:5000'
        if (self.user_env.get('REGISTRY_HOST') is not None):
            return self.build_config.get('REGISTRY_HOST')
        
        ops_config_map = self.kube_client.get_config_map('config')
        if ops_config_map is not None:
            if 'annotations' in ops_config_map.get('metadata', {}):
                annotations = ops_config_map['metadata']['annotations']
                if 'registry_host' in annotations:
                    registry_host = annotations['registry_host']

        return registry_host
        

    def create_docker_file(self) -> str:
        """
        Create a Dockerfile in the current directory.
        """
        source = self.build_config.get("source")
        
        dockerfile_content = f"FROM {source}\n"
        if 'file' in self.build_config:
            requirement_file = self.get_requirements_file_from_kind()
            dockerfile_content += f"COPY ./{requirement_file} /tmp/{requirement_file}\n"
        dockerfile_content += "RUN echo \"/bin/extend\"\n"
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

        tmpdirname = tempfile.mkdtemp()
        if 'file' in self.build_config:
            # decode base64 self.build_config.get('file')
            requirements = base64.b64decode(self.build_config.get('file')).decode('utf-8')
            
            requirement_file = self.get_requirements_file_from_kind()
            with open(os.path.join(tmpdirname, requirement_file), 'w') as f:
                f.write(requirements)
        
        dockerfile_path = os.path.join(tmpdirname, "Dockerfile")
        with open(dockerfile_path, "w") as dockerfile:
            dockerfile.write(self.create_docker_file())
        
        # check if the unzipped directory contains a Dockerfile and is not empty.
        if not self.check_unzip_dir(tmpdirname):
            return None

        # Create a ConfigMap for the build context
        cm = self.kube_client.post_config_map(
            cm_name=self.cm,
            file_or_dir=tmpdirname,
            namespace="nuvolaris",
        )

        shutil.rmtree(tmpdirname)

        if not cm:
            return None

        # retrieve credentials to access the registry
        #

        job_template = self.create_build_job(image_name)
        job = self.kube_client.post_job(self.job_name, job_template)
        if not job:
            return None

        return job

    
    def check_unzip_dir(self, unzip_dir: str) -> bool:
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
        registry_image_name = f"{self.registry_host}/{image_name}"

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
                                    "secretName": "registry-pull-secret",
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
                                    f"buildctl build --frontend=dockerfile.v0 --local context=/workspace --local dockerfile=/workspace --output=type=image,name={registry_image_name},push=true"
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
