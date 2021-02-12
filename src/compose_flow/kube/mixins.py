"""
Compose subcommand
"""
import base64
from functools import lru_cache
import os
import pathlib
import sh
import shutil
import typing
from typing import List
import urllib
import yaml


from compose_flow import errors
from compose_flow.config import get_config
from compose_flow.kube.checks import (
    BaseChecker,
    ManifestChecker,
    AnswersChecker,
    ValuesChecker,
)
from compose_flow.utils import render, render_jinja, get_kv, yaml_dump, yaml_load

CLUSTER_LS_FORMAT = "{{.Cluster.Name}}: {{.Cluster.ID}}"
PROJECT_LS_FORMAT = "{{.Project.Name}}: {{.Project.ID}}"

EXCLUDE_PROFILES = ["local"]

NONFATAL_ERROR_MESSAGES = ['strconv.ParseFloat: parsing "']

if typing.TYPE_CHECKING:
    from compose_flow.commands.workflow import Workflow


def render_config(workflow: "Workflow", config: dict) -> dict:
    # render the config prior to returning it
    content = yaml_dump(config)
    rendered_content = render(content, env=workflow.environment.data)

    rendered_config = yaml_load(rendered_content)

    print(f"rendered_config={rendered_config}")

    return rendered_config


class KubeMixIn(object):
    """
    Mix-in for generic Kubernetes CLI interactions
    """

    kubectl_command = "rancher kubectl"

    @property
    @lru_cache()
    def config(self):
        return get_config(self.workflow)

    @property
    @lru_cache()
    def rendered_config(self):
        return render_config(self.workflow, self.config)

    @property
    def rancher_config(self):
        return self.get_rancher_config()

    def get_rancher_config(self, rendered: bool = False):
        config = self.config
        if rendered:
            config = self.rendered_config

        return config["rancher"]

    @property
    def remotes(self):
        """Section from the global app config for accessing defaults"""
        return self.workflow.app_config.get("remotes")

    @property
    def secret_name(self):
        # k8s doesn't support _ in names
        return self.workflow.config_name.replace("_", "-")

    @staticmethod
    def _is_url(path):
        return urllib.parse.urlparse(path).scheme != ""

    # check methods to validate setup
    def _check_kube_context(self):
        """
        Checks to see if there is a kubecontext configured
        """
        try:
            self.execute("kubectl config current-context")
        except sh.ErrorReturnCode_1 as exc:  # pylint: disable=E1101
            message = exc.stderr.decode("utf8").strip().lower()

            if "current-context is not set" in message:
                raise errors.MissingKubeContext(
                    "No current context configured in kubectl!"
                )

    def _check_kube_namespace(self):
        """
        Checks for existence of the target namespace for native kubectl.

        If not found, attempt to create it.
        """
        try:
            self.execute(f"{self.kubectl_command} get namespace {self.namespace}")
        except sh.ErrorReturnCode_1 as exc:  # pylint: disable=E1101
            message = exc.stderr.decode("utf8").strip().lower()

            if f'namespaces "{self.namespace}" not found' in message:
                self.logger.warning(
                    "Namespace '%s' not found - attempting to create it...",
                    self.namespace,
                )
                self.execute(
                    f"{self.kubectl_command} create namespace {self.namespace}"
                )

    def _check_rancher_namespace(self):
        """
        Checks for existence of the target namespace for Rancher.

        If not found, attempt to create it.
        """
        namespaces = (
            self.execute("rancher namespace ls --quiet")
            .stdout.decode("utf8")
            .strip()
            .split("\n")
        )

        if self.namespace not in namespaces:
            self.logger.warning(
                "Namespace '%s' not found - attempting to create it...", self.namespace
            )
            self.execute(f"rancher namespaces create {self.namespace}")

    # Secret management methods for use by Backends
    def _list_secrets(self):
        return self.execute(
            f"{self.kubectl_command} get secrets --namespace {self.namespace}"
        )

    def _get_secret(self, name: str):
        return self.execute(
            f"{self.kubectl_command} get secrets --namespace {self.namespace} -o yaml {name}"
        )

    def _read_secret_env(self, name: str) -> str:
        """
        Reads environment from a Secret
        """
        try:
            raw_secret = self._get_secret(name)
            self.secret_exists = True
        except sh.ErrorReturnCode_1 as exc:  # pylint: disable=E1101
            message = exc.stderr.decode("utf8").strip().lower()

            if f'secrets "{self.secret_name}" not found' in message:
                self.secret_exists = False
                raise errors.NoSuchConfig(
                    f"secret name={self.secret_name} in namespace={self.namespace} not found"
                )

            raise

        secret_yaml = yaml.safe_load(raw_secret.stdout)
        payload = secret_yaml.get("data")
        if not payload or "_env" not in payload:
            raise errors.NoSuchConfig("secret name={self.secret_name} is empty")

        return base64.b64decode(secret_yaml["data"]["_env"]).decode("utf8")

    def _write_secret_env(self, name: str, path: str) -> None:
        """
        Saves an environment into a Secret
        """
        with open(path, "r") as stream:
            b64_env = base64.b64encode(stream.read().encode()).decode("utf8")

        patch_string = f'{{"data": {{"{self.env_key}": "{b64_env}"}}}}'
        if not self.secret_exists:
            try:
                self.execute(
                    f"{self.kubectl_command} create secret generic --namespace {self.namespace} {self.secret_name}"
                )
            except sh.ErrorReturnCode_1 as exc:  # pylint: disable=E1101
                message = exc.stderr.decode("utf8").strip().lower()

                if f'secrets "{self.secret_name}" already exists' not in message:
                    raise

        self.execute(
            f"{self.kubectl_command} patch secrets --namespace {self.namespace} {self.secret_name} --patch '{patch_string}'"
        )

    def _remove_secret(self, name: str) -> None:
        """
        Removes a Secret corresponding to an environment
        """
        self.execute(
            f"{self.kubectl_command} delete secrets --namespace {self.namespace} {self.secret_name}"
        )

    # Native Kube context management logic
    def switch_kube_context(self):
        """
        Switch current kubectl context to target specified cluster based on environment
        """
        profile_name = self.workflow.args.profile
        context_mapping = self.config.get("kubecontexts", {})

        target_context = context_mapping.get(profile_name, profile_name)
        try:
            self.execute(f"kubectl config use-context {target_context}")
        except sh.ErrorReturnCode_1:  # pylint: disable=E1101
            raise errors.InvalidTargetCluster(
                "No context is defined for profile {}!\n\n"
                "Please specify a corresponding context in your kubeconfig file "
                "or map this profile name to an existing context "
                "in the 'kubecontexts' section of compose-flow.yml".format(profile_name)
            )

    # Rancher context management logic
    @property
    @lru_cache()
    def cluster_listing(self):
        cluster_ls_command = f"rancher cluster ls --format '{CLUSTER_LS_FORMAT}'"
        output = str(self.execute(cluster_ls_command)).strip()
        for err in NONFATAL_ERROR_MESSAGES:
            if err in output:
                output = output.replace(err, "")
        return yaml.load(output)

    @property
    def cluster_name(self):
        """
        Get the cluster name for the specified target environment.

        If profile_name is in the compose-flow.yml Rancher cluster mapping,
        use its value - otherwise check the global remote config,
        then finally use workflow.args.profile if nothing else is defined
        """
        profile_name = self.workflow.args.profile
        default_cluster = (
            self.remotes.get(profile_name, {}).get("rancher", {}).get("cluster")
        )
        cluster_mapping = self.rancher_config.get("clusters", {})

        if profile_name in EXCLUDE_PROFILES:
            raise errors.InvalidTargetCluster(
                "Invalid profile '{0}' for default cluster logic - please "
                "specify an explicit cluster mapping in compose-flow.yml and "
                "use a profile other than '{0}'".format(profile_name)
            )

        # If project defines
        configured_name = cluster_mapping.get(profile_name)
        if configured_name:
            return configured_name
        elif default_cluster:
            return default_cluster
        else:
            return profile_name

    @property
    def cluster_id(self):
        return self.cluster_listing[self.cluster_name]

    @property
    def project_name(self):
        default_project = (
            self.remotes.get(self.workflow.args.profile, {})
            .get("rancher", {})
            .get("project")
        )
        configured_project = self.rancher_config.get("project")
        if configured_project:
            return configured_project
        elif default_project:
            return default_project
        else:
            raise errors.MissingRancherProject(
                "ERROR: You must configure a Rancher project in "
                "compose-flow.yml or .compose/config.yml in order "
                "to use Rancher as a backend or deployment target!"
            )

    def switch_rancher_context(self):
        """
        Switch Rancher CLI context to target specified cluster based on environment
        and specified project name from compose-flow.yml
        """
        # Get the project name specified in compose-flow.yml
        target_project_name = self.project_name

        current_context = (
            self.execute("rancher context current")
            .stdout.decode("utf8")
            .strip()
            .split(" ")
        )
        correct_cluster = current_context[0] == f"Cluster:{self.cluster_name}"
        correct_project = current_context[1] == f"Project:{target_project_name}"

        if correct_cluster and correct_project:
            # Don't do anything if context is already correct
            return

        base_context_switch_command = "rancher context switch "
        name_context_switch_command = base_context_switch_command + target_project_name
        try:
            self.logger.info(name_context_switch_command)
            self.execute(name_context_switch_command)
        except sh.ErrorReturnCode_1 as exc:  # pylint: disable=E1101
            stderr = str(exc.stderr)
            if "Multiple resources of type project found for name" in stderr:
                self.logger.info(
                    "Multiple clusters have a project called %s - "
                    "switching context by Project ID",
                    target_project_name,
                )
                # Choose the one that matches target cluster ID
                opts = stderr[stderr.find("[") + 1 : stderr.find("]")].split(" ")
                target_project_id = [o for o in opts if self.cluster_id in o][0]

                id_context_switch_command = (
                    base_context_switch_command + target_project_id
                )
                self.logger.info(id_context_switch_command)
                self.execute(id_context_switch_command)
            else:
                raise

    # YAML rendering and deployment methods
    def get_app_deploy_command(self, app: dict, target: str = "rancher") -> str:
        """
        Construct command to install or upgrade a Rancher app
        depending on whether or not it is already deployed.
        """

        app_name = app["name"]
        version = app["version"]
        namespace = app["namespace"]
        chart = app["chart"]
        raw = app.get("raw", False)

        answers_path = app.get("answers")
        values_path = app.get("values")

        use_answers = True
        if answers_path and values_path:
            raise ValueError(
                "A single app cannot use both answers (flat) and values (nested) - pick one!"
            )
        elif answers_path:
            if target == "helm":
                self.logger.warning(
                    "Helm only supports nested values - please "
                    "switch from answers to values in compose-flow.yml"
                )
            rendered_path = self.render_answers(answers_path, app_name, raw)
        elif values_path:
            use_answers = False
            rendered_path = self.render_values(values_path, app_name, raw)
        else:
            self.logger.warning(
                "Neither answers nor values were provided - using default chart configuration"
            )
            rendered_path = None

        app_list = getattr(self, f"list_{target}_apps")()
        upgrade_command_method = getattr(self, f"get_{target}_app_upgrade_command")
        install_command_method = getattr(self, f"get_{target}_app_install_command")

        if app_name in app_list:
            return upgrade_command_method(
                app_name, rendered_path, namespace, chart, version, use_answers
            )
        else:
            return install_command_method(
                app_name, rendered_path, namespace, chart, version, use_answers
            )

    def list_helm_apps(self) -> List[str]:
        return str(self.execute("helm ls -q --all --all-namespaces")).split("\n")

    def get_helm_app_install_command(
        self,
        app_name: str,
        rendered_path: str,
        namespace: str,
        chart: str,
        version: str,
        use_answers: bool = False,
    ):
        return f"helm install -f {rendered_path} --namespace {namespace} --version {version} {app_name} {chart}"

    def get_helm_app_upgrade_command(
        self,
        app_name: str,
        rendered_path: str,
        namespace: str,
        chart: str,
        version: str,
        use_answers: bool = False,
    ):
        return f"helm upgrade -f {rendered_path} --namespace {namespace} --version {version} {app_name} {chart}"

    def list_pods(self, namespace: str = None):
        if namespace:
            namespace_command = f" -n {namespace} "
        else:
            namespace_command = ""
        return str(self.execute(f"{self.kubectl_command} get pods {namespace_command}"))

    def list_rancher_apps(self) -> List[str]:
        return str(self.execute("rancher apps ls --format '{{.App.Name}}'")).split("\n")

    def get_rancher_app_install_command(
        self,
        app_name: str,
        rendered_path: str,
        namespace: str,
        chart: str,
        version: str,
        use_answers: bool,
    ):
        cmd = "rancher apps install "
        if rendered_path:
            if use_answers:
                cmd += f"--answers {rendered_path}"
            else:
                cmd += f"--values {rendered_path}"
        return cmd + f" --namespace {namespace} --version {version} {chart} {app_name}"

    def get_rancher_app_upgrade_command(
        self,
        app_name: str,
        rendered_path: str,
        namespace: str,  # unused here, included for parity with Helm
        chart: str,
        version: str,
        use_answers: bool,
    ):
        cmd = "rancher apps upgrade "
        if rendered_path:
            if use_answers:
                cmd += f"--answers {rendered_path}"
            else:
                cmd += f"--values {rendered_path}"

        return cmd + f" {app_name} {version}"

    def list_rancher_namespaces(self) -> List[str]:
        return str(
            self.execute("rancher namespaces ls --format '{{.Namespace.ID}}'")
        ).split("\n")

    def create_rancher_namespace(self, namespace, dry_run=False):
        creation_command = f"rancher namespaces create {namespace}"

        print(f"Creating namespace {namespace} in project {self.project_name}")
        if not dry_run:
            try:
                self.execute(creation_command)
            except sh.ErrorReturnCode_1 as exc:  # pylint: disable=E1101
                message = exc.stderr.decode("utf8").strip()
                if "code=AlreadyExists" in message:
                    raise errors.RancherNamespaceAlreadyExists(
                        f"Namespace {namespace} already exists in another project!"
                    )
                else:
                    raise

    def upsert_rancher_namespaces(self, dry_run) -> str:
        namespaces = self.get_rancher_namespaces()
        existing = self.list_rancher_namespaces()

        for ns in namespaces:
            if ns in existing:
                continue
            else:
                self.create_rancher_namespace(ns, dry_run)

    def get_kubectl_command(
        self, manifest: dict, kubectl_prefix: str = "kubectl"
    ) -> str:
        """Construct command to apply a Kubernetes YAML manifest using kubectl."""

        deploy_label = self.workflow.config_name

        raw_path = manifest["path"]
        deploy_label = manifest.get("label")
        namespace = manifest.get("namespace")
        action = manifest.get("action", "apply")
        raw = manifest.get("raw", False)

        namespace_str = f"--namespace {namespace} " if namespace else ""
        deploy_label_str = "-l deploy={deploy_label} --prune " if deploy_label else ""

        command = (
            f"{kubectl_prefix} {namespace_str}{action} {deploy_label_str}--validate -f "
        )

        # Allow URL manifests to be provided but do not template them
        if self._is_url(raw_path):
            self.logger.info("Skip rendering for URL manifest %s", raw_path)
            command += raw_path
        else:
            if os.path.isdir(raw_path):
                rendered_path = self.render_nested_manifests(raw_path, raw)
                command += rendered_path + " --recursive"
            elif os.path.isfile(raw_path):
                rendered_path = self.render_manifest(raw_path, raw)
                command += rendered_path
            else:
                raise errors.MissingManifest(
                    "Missing manifest at path: {}".format(manifest)
                )

        return command

    def get_rke_deploy_command(self):
        raw_config = get_config(self.workflow)["rke"]["config"]
        rendered_config = f"compose-flow-{self.workflow.args.profile}-rke.yml"
        self.render_single_yaml(raw_config, rendered_config)
        return f"rke up --config {rendered_config}"

    def get_extra_section(self, section: str) -> list:
        extras = self.rancher_config.get("extras")
        if extras:
            env_extras = extras.get(self.workflow.args.profile)
            if env_extras:
                return env_extras.get(section, [])

        return []

    def get_helm_apps(self) -> list:
        return self.config["helm"]

    def get_apps(self) -> list:
        rancher_config = self.get_rancher_config(rendered=True)
        default_apps = rancher_config.get("apps", [])

        print(f"apps={default_apps}")

        extra_apps = self.get_extra_section("apps")

        return default_apps + extra_apps

    def get_kubectl_manifests(self) -> list:
        return self.config.get("kubectl_manifests", [])

    def get_rancher_namespaces(self) -> list:
        default_namespaces = self.rancher_config.get("namespaces", [])
        extra_namespaces = self.get_extra_section("namespaces")

        return default_namespaces + extra_namespaces

    def get_rancher_manifests(self) -> list:
        default_manifests = self.rancher_config.get("manifests", [])
        extra_manifests = self.get_extra_section("manifests")

        return default_manifests + extra_manifests

    def get_manifest_filename(self, manifest_path: str) -> str:
        escaped_path = (
            manifest_path.replace("../", "")
            .replace("./", "")
            .replace("/", "-")
            .replace(".yaml", ".yml")
            .rstrip("-")
        )
        return f"compose-flow-{self.cluster_name}-manifest-{escaped_path}"

    def get_answers_filename(self, app_name: str) -> str:
        return f"compose-flow-{self.cluster_name}-{app_name}-answers.yml"

    def get_values_filename(self, app_name: str) -> str:
        return f"compose-flow-{self.cluster_name}-{app_name}-values.yml"

    def render_single_yaml(
        self,
        input_path: str,
        output_path: str,
        checker: BaseChecker = None,
        raw: bool = False,
    ) -> None:
        """
        Read in single YAML file from specified path, render environment variables,
        then write out to a known location in the working dir.
        """
        self.logger.info("Rendering YAML at %s to %s", input_path, output_path)

        with open(input_path, "r") as fh:
            content = fh.read()

        if not raw:
            env = dict(get_kv(self.workflow.environment.render(), multiple=True))

            rendered = render(content, env=env)
            rendered = render_jinja(rendered, env=env)
        else:
            rendered = content

        if checker:
            check_errors = checker.check(rendered)

            if check_errors:
                raise errors.ManifestCheck("\n".join(check_errors))

        with open(output_path, "w") as fh:
            fh.write(rendered)

    @lru_cache()
    def render_manifest(self, manifest_path: str, raw: bool) -> str:
        """Render the specified manifest YAML and return the path to the rendered file."""
        rendered_path = self.get_manifest_filename(manifest_path)
        self.render_single_yaml(manifest_path, rendered_path, ManifestChecker(), raw)

        return rendered_path

    @lru_cache()
    def render_nested_manifests(self, dir_path: str, raw: bool) -> str:
        directory = pathlib.Path(dir_path)
        manifests = directory.glob("**/*.y*ml")
        rendered_path = self.get_manifest_filename(dir_path)

        # reset rendered_path to avoid deploying lingering files
        if os.path.isdir(rendered_path):
            shutil.rmtree(rendered_path)

        for manifest in manifests:
            render_dest = os.path.join(rendered_path, str(manifest).lstrip(dir_path))
            print(render_dest)
            parent_dest = os.path.dirname(render_dest)

            os.makedirs(parent_dest, mode=0o750, exist_ok=True)
            self.render_single_yaml(manifest, render_dest, ManifestChecker(), raw)
        return rendered_path

    @lru_cache()
    def render_answers(self, answers_path: str, app_name: str, raw: bool) -> str:
        """Render the specified manifest YAML and return the path to the rendered file."""
        rendered_path = self.get_answers_filename(app_name)
        self.render_single_yaml(answers_path, rendered_path, AnswersChecker(), raw)

        return rendered_path

    @lru_cache()
    def render_values(self, answers_path: str, app_name: str, raw: bool) -> str:
        """Render the specified manifest YAML and return the path to the rendered file."""
        rendered_path = self.get_values_filename(app_name)
        self.render_single_yaml(answers_path, rendered_path, ValuesChecker(), raw)

        return rendered_path
