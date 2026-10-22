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

"""Tenant routes matching the CLI's nginx/Traefik streaming and S3 paths."""
import re
from copy import deepcopy

from .kube_client import ProvisioningError


def route_context(apihost):
    spec = apihost.get("spec", {})
    ingress_class = spec.get("ingressClassName")
    if ingress_class is None:
        ingress_class = apihost.get("metadata", {}).get("annotations", {}).get("kubernetes.io/ingress.class")
    rules = spec.get("rules", [])
    hostname = rules[0].get("host", "") if rules else ""
    if ingress_class not in ("nginx", "traefik") or not isinstance(hostname, str) or not re.fullmatch(
        r"[a-z0-9](?:[a-z0-9.-]*[a-z0-9])?", hostname
    ):
        raise ProvisioningError("Unsupported or unavailable cluster ingress configuration")
    return ingress_class, hostname, bool(spec.get("tls"))


def tenant_routes(user, context, services, streamer, uid):
    ingress_class, domain, tls = context
    hostname = f"{user}.{domain}"
    if len(hostname) > 253:
        raise ProvisioningError("Tenant hostname is too long", 400)
    owner = [{"apiVersion": "openserverless.org/v1", "kind": "WhiskUser",
              "name": user, "uid": uid}]
    annotations = {"nginx.ingress.kubernetes.io/proxy-body-size": "48m"}
    if ingress_class == "nginx":
        annotations.update({f"nginx.ingress.kubernetes.io/proxy-{key}-timeout": "300"
                            for key in ("connect", "read", "send")})
    else:
        annotations.update({f"traefik.ingress.kubernetes.io/transport.respondingTimeouts.{key}Timeout": "600"
                            for key in ("idle", "read", "write")})
    if tls:
        annotations["cert-manager.io/cluster-issuer"] = "letsencrypt-prod"
        if ingress_class == "nginx":
            annotations["nginx.ingress.kubernetes.io/force-ssl-redirect"] = "true"
        else:
            annotations["traefik.ingress.kubernetes.io/router.tls"] = "true"
            annotations["traefik.ingress.kubernetes.io/router.entrypoints"] = "websecure,web"

    def ingress(suffix, paths, extra=None):
        meta = {"name": f"{user}-{suffix}", "namespace": "openserverless",
                "ownerReferences": deepcopy(owner), "annotations": {**annotations, **(extra or {})}}
        spec = {"ingressClassName": ingress_class,
                "rules": [{"host": hostname, "http": {"paths": paths}}]}
        if tls:
            spec["tls"] = [{"hosts": [hostname], "secretName": "streamer-api-tls"}]
        return {"apiVersion": "networking.k8s.io/v1", "kind": "Ingress", "metadata": meta, "spec": spec}

    def path(value, service="openserverless-streamer-api", port=8080, path_type="Prefix"):
        return {"path": value, "pathType": path_type,
                "backend": {"service": {"name": service, "port": {"number": port}}}}

    result = []
    if streamer:
        result.append(ingress("my-streamer-ingress", [path("/web"), path("/action")]))
        for mode in ("web", "action"):
            middleware_name = f"{user}-stream-{mode}-rewrite"
            if ingress_class == "traefik":
                result.append({"apiVersion": "traefik.io/v1alpha1", "kind": "Middleware",
                               "metadata": {"name": middleware_name, "namespace": "openserverless", "ownerReferences": deepcopy(owner)},
                               "spec": {"replacePathRegex": {"regex": f"/stream/{mode}(/|$)(.*)",
                                                             "replacement": f"/{mode}/{user}/$2"}}})
                extra = {"traefik.ingress.kubernetes.io/router.middlewares": f"openserverless-{middleware_name}@kubernetescrd"}
                paths = [path(f"/stream/{mode}")]
            else:
                extra = {"nginx.ingress.kubernetes.io/use-regex": "true",
                         "nginx.ingress.kubernetes.io/rewrite-target": f"/{mode}/{user}/$2"}
                paths = [path(f"/stream/{mode}(/|$)(.*)", path_type="ImplementationSpecific")]
            result.append(ingress(f"my-streamer-{mode}-ingress", paths, extra))
    if "seaweedfs" in services or "minio" in services:
        backend = "seaweedfs" if "seaweedfs" in services else "minio"
        result.append(ingress("my-s3-ingress", [path(f"/{user}-web", backend, 9000),
                                               path(f"/{user}-data", backend, 9000)],
                              {"nginx.ingress.kubernetes.io/proxy-body-size": "1024m"}))
    return result
