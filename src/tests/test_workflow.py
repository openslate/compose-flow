import shlex

from unittest import TestCase, mock

from compose_flow import utils
from compose_flow.commands import Workflow

TEST_PROJECT_NAME = 'test_project_name'


class WorkflowTestCase(TestCase):
    @mock.patch('compose_flow.commands.workflow.print')
    @mock.patch('compose_flow.commands.workflow.pkg_resources')
    def test_version(self, *mocks):
        """
        Ensure the --version arg just returns the version
        """
        version = '0.0.0-test'

        pkg_resources_mock = mocks[0]
        pkg_resources_mock.require.return_value = [mock.Mock(version=version)]

        command = shlex.split('--version')
        workflow = Workflow(argv=command)

        workflow.run()

        print_mock = mocks[1]
        print_mock.assert_called_with(version)


@mock.patch('compose_flow.commands.workflow.PROJECT_NAME', new=TEST_PROJECT_NAME)
class WorkflowArgsTestCase(TestCase):
    """
    Tests for parsing command line arguments
    """
    def test_sensible_defaults_no_env(self, *mocks):
        """
        Test sensible defaults when no environment is defined
        """
        command = shlex.split('publish')
        workflow = Workflow(argv=command)

        self.assertEqual(None, workflow.args.environment)
        self.assertEqual(None, workflow.args.remote)
        self.assertEqual(TEST_PROJECT_NAME, workflow.args.config_name)
        self.assertEqual(TEST_PROJECT_NAME, workflow.args.project_name)

    def test_sensible_defaults_with_env(self, *mocks):
        """
        Test sensible defaults when an environment is defined
        """
        env = 'dev'
        command = shlex.split(f'-e {env} publish')
        workflow = Workflow(argv=command)

        self.assertEqual(env, workflow.args.environment)
        self.assertEqual(env, workflow.args.remote)
        self.assertEqual(f'{env}-{TEST_PROJECT_NAME}', workflow.args.config_name)
        self.assertEqual(TEST_PROJECT_NAME, workflow.args.project_name)

    def test_sensible_defaults_with_env_and_project(self, *mocks):
        """
        Test sensible defaults when an environment and project name is defined
        """
        env = 'dev'
        command = shlex.split(f'-e {env} --project-name foo publish')
        workflow = Workflow(argv=command)

        self.assertEqual(env, workflow.args.environment)
        self.assertEqual(env, workflow.args.remote)
        self.assertEqual(f'{env}-foo', workflow.args.config_name)
        self.assertEqual('foo', workflow.args.project_name)