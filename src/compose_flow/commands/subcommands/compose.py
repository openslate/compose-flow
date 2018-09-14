"""
Compose subcommand
"""
import argparse
import logging
import os

from .passthrough_base import PassthroughBaseSubcommand

from compose_flow import docker, errors

DEFAULT_COMPOSE_FILENAME = 'docker-compose.yml'


class Compose(PassthroughBaseSubcommand):
    """
    Subcommand for running compose commands
    """
    command_name = 'docker-compose'
    dirty_working_copy_okay = True

    def __init__(self, *args, check_profile=True, version=None, **kwargs):
        self.check_profile = check_profile
        self._version = version

        super().__init__(*args, **kwargs)

    def get_command(self):
        command = super().get_command()

        if self.env.env_name:
            command.extend(['--project-name', self.env.project_name])

        profile = self.workflow.profile
        command.extend([
            '-f', profile.filename,
        ])

        return command

    def handle(self, extra_args: list=None) -> [None, str]:
        # check the profile to make sure it defines all the needed environment variables
        if self.check_profile:
            self.workflow.profile.check()

        super().handle(extra_args=extra_args)

    @property
    def logger(self) -> logging.Logger:
        return logging.getLogger(f'{__name__}.{self.__class__.__name__}')

    @property
    def version(self):
        """
        Returns the version in the environment, unless it was overridden in this Compose instance
        """
        return self._version or self.env.version
