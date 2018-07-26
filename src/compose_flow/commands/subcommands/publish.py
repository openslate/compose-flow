import logging

from functools import lru_cache

import sh

from .base import BaseSubcommand
# from .compose import Compose


class Publish(BaseSubcommand):
    """
    Subcommand for building and pushing Docker images
    """
    def build(self):
        self.compose.run(extra_args=['build'])

    @property
    @lru_cache()
    def compose(self):
        """
        Returns a Compose subcommand
        """
        from .compose import Compose

        return Compose(self.workflow)

    @classmethod
    def fill_subparser(cls, parser, subparser) -> None:
        pass

    def handle(self):
        self.build()

        self.push()

    @property
    def logger(self):
        return logging.getLogger(f'{__name__}.{self.__class__.__name__}')

    def push(self):
        docker_images = set()
        for service_data in self.profile.data['services'].values():
            if service_data.get('build'):
                docker_images.add(service_data.get('image'))

        for docker_image in docker_images:
            if len(docker_images) > 1:
                self.logger.info(f'pushing {docker_image}')

            if self.args.dry_run:
                self.logger.info(f'docker push {docker_image}')
            else:
                sh.docker('push', docker_image, _fg=True)
