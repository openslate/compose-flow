import shlex

from unittest import TestCase, mock

from compose_flow import utils
from compose_flow.commands import ComposeFlow


class PublishTestCase(TestCase):
    @mock.patch('compose_flow.commands.subcommands.env.utils')
    @mock.patch('compose_flow.commands.subcommands.env.docker')
    def test_profile_env(self, *mocks):
        """
        Ensure the VERSION is updated
        """
        docker_mock = mocks[0]
        docker_mock.get_config.return_value = "FOO=1\nBAR=2"

        utils_mock = mocks[1]
        utils_mock.get_tag_version.return_value = '0.0.1'
        utils_mock.render = utils.render

        command = shlex.split('-e dev publish')
        flow = ComposeFlow(argv=command)

        flow.run()

        env_data = flow.subcommand.env.data

        self.assertEqual(True, 'VERSION' in env_data)
