import os
import shlex
from unittest import mock

from compose_flow import errors
from compose_flow.commands.subcommands.env import Env, RUNTIME_PLACEHOLDER
from compose_flow.commands import Workflow

from tests import BaseTestCase


# noinspection PyUnusedLocal
@mock.patch("compose_flow.commands.workflow.PROJECT_NAME", new="testdirname")
@mock.patch("compose_flow.config.read_project_config", return_value=dict())
class EnvTestCase(BaseTestCase):
    def test_backend_default(self, *mocks):
        """
        Ensure a local backend is returned
        """
        flow = mock.Mock()
        flow.args.remote = None

        env = Env(flow)

        self.assertEqual(env.backend.__class__.__name__, "LocalBackend")

    @mock.patch("compose_flow.commands.subcommands.env.get_backend")
    def test_backend_from_app_config(self, *mocks):
        """
        Ensure a local backend is returned
        """
        backend_name = "rancher"

        flow = mock.Mock()
        flow.args.remote = "dev"

        flow.app_config = {
            "remotes": {"dev": {"environment": {"backend": backend_name}}}
        }

        get_backend_mock = mocks[0]
        get_backend_mock.return_value = "RancherBackend"

        env = Env(flow)
        backend = env.backend

        self.assertEqual(backend, "RancherBackend")

        get_backend_mock.assert_called_with(backend_name, workflow=flow)

    def test_config_name_arg(self, *mocks):
        """
        Ensure the config arg updates the config name

        TODO: this should move to test_workflow
        """
        config_name = "dev-test"
        command = shlex.split(f"-e dev --config-name={config_name} env cat")
        flow = Workflow(argv=command)
        env = Env(flow)

        self.assertEqual(flow.config_name, config_name)

    # noinspection PyMethodMayBeStatic
    def test_data_not_loaded_when_cache_is_empty_dict(self, *mocks):
        workflow = mock.MagicMock()
        workflow.args.environment = None
        workflow.args.iter.return_value = []

        env = Env(workflow)

        # setup mocks on the env instance
        env.load = mock.Mock()
        env.load.return_value = {}

        # prime the cache with an empty dict to ensure load is not called
        env._data = {}

        # noinspection PyStatementEffect
        env.data

        # noinspection PyUnresolvedReferences
        env.load.assert_not_called()

    def test_default_config_name(self, *mocks):
        """
        Ensure the default config is given

        TODO: this should move to test_workflow
        """
        command = shlex.split("-e dev env cat")
        flow = Workflow(argv=command)
        env = Env(flow)

        self.assertEqual(flow.config_name, "dev-testdirname")

    @mock.patch("compose_flow.commands.subcommands.env.get_backend")
    def test_empty_env_value(self, *mocks):
        """Ensure that a value can be empty if the line ends with an equals"""
        get_backend_mock = mocks[0]
        get_backend_mock.return_value.read.return_value = "FOO="

        command = shlex.split("-e dev env cat")
        flow = Workflow(argv=command)

        self.assertEquals("", flow.environment.data["FOO"])

    @mock.patch("compose_flow.commands.subcommands.env.get_backend")
    def test_load_ro(self, *mocks):
        """
        Ensures that env.load does not reset the VERSION var

        The DOCKER_IMAGE and VERSION vars should only be modified when publishing an image
        In all other commands, the environment should be read-only
        """
        version = "1.2.3"
        docker_image = "foo:bar"

        get_backend_mock = mocks[0]
        get_backend_mock.return_value.read.return_value = (
            f"FOO=1\nBAR=2\nVERSION={version}\nDOCKER_IMAGE={docker_image}"
        )

        command = shlex.split("-e dev env cat")
        flow = Workflow(argv=command)

        flow.run()

        env = flow.subcommand

        self.assertEqual(version, env.data["VERSION"])
        self.assertEqual(docker_image, env.data["DOCKER_IMAGE"])

        self.assertEqual(
            ["BAR", "DOCKER_IMAGE", "FOO", "VERSION"], sorted(env._persistable_keys)
        )

    @mock.patch("compose_flow.commands.subcommands.env.get_backend")
    def test_load_runtime(self, *mocks):
        """
        Ensures that runtime variables are able to be viewed/edited without being set
        """
        version = "1.2.3"
        docker_image = "foo:bar"

        bar_env_val = "bar"
        os.environ["BAR"] = bar_env_val

        get_backend_mock = mocks[0]
        get_backend_mock.return_value.read.return_value = (
            f"FOO={RUNTIME_PLACEHOLDER}\nBAR={RUNTIME_PLACEHOLDER}\n"
            f"VERSION={version}\nDOCKER_IMAGE={docker_image}"
        )

        command = shlex.split("-e dev env cat")
        flow = Workflow(argv=command)

        flow.run()

        env = flow.subcommand

        self.assertEqual(RUNTIME_PLACEHOLDER, env.data["FOO"])
        self.assertEqual(bar_env_val, env.data["BAR"])

    @mock.patch("compose_flow.commands.subcommands.env.get_backend")
    def test_missing_runtime_error(self, *mocks):
        """
        Ensures that runtime variables must be set to run any compose commands
        """
        version = "1.2.3"
        docker_image = "foo:bar"

        get_backend_mock = mocks[0]
        get_backend_mock.return_value.read.return_value = (
            f"FOO={RUNTIME_PLACEHOLDER}\nVERSION={version}\nDOCKER_IMAGE={docker_image}"
        )

        command = shlex.split("-e dev compose config")
        flow = Workflow(argv=command)

        assert os.environ.get("FOO") is None
        with self.assertRaises(errors.RuntimeEnvError):
            # noinspection PyStatementEffect
            flow.profile.data["services"]

    @mock.patch("compose_flow.commands.subcommands.env.get_backend")
    def test_rendered_extends(self, *mocks):
        """Ensure the rendered config includes extended variables"""

        def backend_read(config_name):
            data = "CF_ENV_EXTENDS_BASENAME=foo"
            if "foo" in config_name:
                data = "FOO=true"

            return data

        get_backend_mock = mocks[0]
        get_backend_mock.return_value.read.side_effect = backend_read

        command = shlex.split("-e dev env cat")
        flow = Workflow(argv=command)

        buf = flow.environment.render()

        self.assertEqual(True, "FOO=true" in buf)
