"""Define checks to be run against Kubernetes YAML"""

from abc import ABC
import logging
from typing import List

import yaml

POD_TEMPLATE_RESOURCES = [
    "DaemonSet",
    "Deployment",
    "ReplicaSet",
    "Job",
    "StatefulSet",
    "CronJob",
]

JOB_TEMPLATE_RESOURCES = ["CronJob"]


class BaseChecker(ABC):
    check_prefix = None

    @property
    def logger(self):
        return logging.getLogger(f"{__name__}.{self.__class__.__name__}")

    def check(self, rendered: str) -> List[str]:
        """Main method that runs all check methods defined on this class."""
        errors = []

        if self.check_prefix is None:
            raise AttributeError("The class attribute `check_prefix` must be non-null!")

        # Load all YAML documents from string `rendered`
        loaded = self._load_rendered_yaml(rendered)

        checks = self._get_all_checks()
        for check in checks:
            result = check(loaded)
            if result:
                errors.append(result)

        return errors

    def _get_all_checks(self):
        """Return a list of the methods on this class which begin with `check_prefix`."""
        this_class = self.__class__

        check_list = [
            getattr(self, func)
            for func in dir(self.__class__)
            if callable(getattr(this_class, func))
            and func.startswith(self.check_prefix)
        ]

        return check_list

    def _load_rendered_yaml(self, rendered: str) -> dict:
        """Load the rendered YAML which is passed in to the `check` method."""
        return [d for d in yaml.safe_load_all(rendered)]


class ManifestChecker(BaseChecker):
    """Check Kubernetes YAML resource manifests."""

    check_prefix = "_check_manifest_"

    def _check_manifest_ingress_annotations(self, documents: list) -> str:
        """Check ingresses for appropriate annotations"""
        ingress_kind = "Ingress"
        internal_value = "internal"
        external_value = "internet-facing"

        missing_metadata_msg = (
            "Ingress resources MUST specify a metadata section including"
            "name, namespace, and appropriate annotations!"
        )
        ingress_error_msg = (
            "Ingress resources MUST specify a scheme annotation to avoid "
            "unintentionally exposing a service to the public Internet!"
        )

        public_ingress_warning = (
            "An ingress resource in this deployment is internet-facing!\n\n"
            "Please ensure you are deploying to a production cluster "
            "and you intend to make your services PUBLICLY accessible!"
        )

        for doc in documents:
            if doc.get("kind") == ingress_kind:
                metadata = doc.get("metadata")
                if metadata is None:
                    return missing_metadata_msg
                annotations = metadata.get("annotations")
                if annotations is None:
                    return ingress_error_msg

                class_anno = annotations.get("kubernetes.io/ingress.class")
                if class_anno != "nginx":
                    print(annotations)
                    has_internal = any(
                        "scheme" in k and internal_value in v
                        for k, v in annotations.items()
                    )
                    has_external = any(
                        "scheme" in k and external_value in v
                        for k, v in annotations.items()
                    )
                    if has_external:
                        self.logger.warn(public_ingress_warning)
                    if not has_internal and not has_external:
                        return ingress_error_msg

    def _check_manifest_resources(self, documents: list) -> str:
        """Check resource types that deploy Pods for resource constraints."""
        for doc in documents:
            kind = doc.get("kind")

            # If this kind defines a job template, pull it out
            if kind in JOB_TEMPLATE_RESOURCES:
                doc = doc.get("spec").get("jobTemplate")
                if doc is None:
                    return f"{kind} resources MUST specify a job template!"

            if kind in POD_TEMPLATE_RESOURCES:
                pod_template = doc.get("spec").get("template")
                if pod_template is None:
                    return f"{kind} resources MUST specify a pod template!"

                pod_spec = pod_template.get("spec")
                if pod_spec is None:
                    return f"{kind} resources MUST specify a pod spec!"

                containers = pod_spec.get("containers")
                if not containers:
                    return f"{kind} resources MUST specify at least one container!"

                init_containers = pod_spec.get("initContainers")
                if init_containers:
                    containers = containers + init_containers

                missing_resources_msg = (
                    f"All containers and initContainers in a {kind}"
                    "must define resource constraints!"
                )
                for cont in containers:
                    resources = cont.get("resources")
                    if not resources:
                        return missing_resources_msg

                    limits = resources.get("limits")
                    if not limits or not limits.get("cpu") or not limits.get("memory"):
                        return missing_resources_msg

                    requests = resources.get("requests")
                    if (
                        not requests
                        or not requests.get("cpu")
                        or not requests.get("memory")
                    ):
                        return missing_resources_msg


class AnswersChecker(BaseChecker):
    check_prefix = "_check_answers_"

    def _check_answers_flat_resources(self, documents: list) -> str:
        """
        Check for resource constraints in Helm answers.

        Assumes the answers are in the flat key:value format required by Rancher.
        """
        if len(documents) > 1:
            return "We only support flat Helm answers! Please provide a single document of key:value pairs."

        answers = documents[0]
        has_resources = False
        has_limits = False
        has_requests = False
        has_memory_request = False
        has_cpu_request = False
        has_memory_limit = False
        has_cpu_limit = False
        for answer in answers.keys():
            if "resources" in answer:
                has_resources = True

            if ".requests" in answer:
                has_requests = True
                if ".requests.memory" in answer:
                    has_memory_request = True
                elif ".requests.cpu" in answer:
                    has_cpu_request = True

            if ".limits" in answer:
                has_limits = True
                if ".limits.memory" in answer:
                    has_memory_limit = True
                if ".limits.cpu" in answer:
                    has_cpu_limit = True

        if not has_resources:
            self.logger.warning(
                "Helm answers do not contain resource constraints! "
                "Please verify that the specified chart has default "
                "resources defined for all containers!"
            )
        else:
            if not has_requests or not has_memory_request or not has_cpu_request:
                return "Answers specify resources but not requests! Please specify both CPU and memory requests."
            if not has_limits or not has_memory_limit or not has_cpu_limit:
                return "Answers specify resources but not limits! Please specify both CPU and memory limits."


class ValuesChecker(BaseChecker):
    check_prefix = "_check_values_"

    def _check_values_flat_resources(self, documents: list) -> str:
        """
        Check for resource constraints in nested Helm values.
        """
        if len(documents) > 1:
            return "We only support flat Helm values! Please provide a single YAML document."
