import logging
import os
import shlex

import sh

from .base import BaseSubcommand


class Deploy(BaseSubcommand):
    """
    Subcommand for deploying an image to the docker swarm
    """
    rw_env = True

    @classmethod
    def fill_subparser(cls, parser, subparser):
        pass

    @property
    def logger(self):
        return logging.getLogger(f'{__name__}.{self.__class__.__name__}')

    def handle(self):
        profile = self.workflow.profile

        # check the profile to make sure it defines all the needed environment variables
        profile.check()

        command = f"""docker stack deploy
          --prune
          --with-registry-auth
          --compose-file {profile.filename}
          {self.env.project_name}"""

        command_split = shlex.split(command)

        self.logger.info(command)

        if not self.args.dry_run:
            executable = getattr(sh, command_split[0])
            executable(*command_split[1:], _env=os.environ)

            self.env.write()
