import logging

import sh

from .base import BaseSubcommand


class Deploy(BaseSubcommand):
    """
    Subcommand for deploying an image to the docker swarm
    """
    @classmethod
    def fill_subparser(cls, parser, subparser):
        pass

    @property
    def logger(self):
        return logging.getLogger(f'{__name__}.{self.__class__.__name__}')

    def handle(self):
        project_name = self.args.project_name

        command = f"""docker stack deploy
          --prune
          --with-registry-auth
          --compose-file {filenames[0]}
          {project_name}"""

        command_split = shlex.split(command)

        self.logger.info(command)

        if not self.args.dry_run:
            executable = getattr(sh, command_split[0])
            executable(*command_split[1:], _env=os.environ)
