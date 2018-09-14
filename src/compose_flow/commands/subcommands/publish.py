import logging

from functools import lru_cache

import sh

from .base import BaseSubcommand
# from .compose import Compose


class Publish(BaseSubcommand):
    """
    Subcommand for building and pushing Docker images
    """
    rw_env = True
    remote_action = True

    def __init__(self, *args, **kwargs):
        if 'load_cf_env' not in kwargs:
            kwargs['load_cf_env'] = self.rw_env

        super().__init__(*args, **kwargs)

    def build(self):
        compose = self.get_compose(check_profile=False)

        compose.run(extra_args=['build'])

    @property
    def compose(self):
        """
        Returns a Compose subcommand
        """
        return self.get_compose()

    @classmethod
    def fill_subparser(cls, parser, subparser) -> None:
        pass

    @lru_cache()
    def get_compose(self, **kwargs):
        from .compose import Compose

        return Compose(self.workflow, **kwargs)

    def handle(self):
        # only load up the basic environment for publish
        self.update_runtime_environment(load_cf_env=False)

        self.build()

        self.push()

    def is_missing_env_arg_okay(self):
        return True

    @property
    def logger(self):
        return logging.getLogger(f'{__name__}.{self.__class__.__name__}')

    def push(self):
        docker_images = set()

        profile = self.workflow.profile
        for service_data in profile.data['services'].values():
            if service_data.get('build'):
                docker_images.add(service_data.get('image'))

        for docker_image in docker_images:
            if len(docker_images) > 1:
                self.logger.info(f'pushing {docker_image}')

            if self.args.dry_run:
                self.logger.info(f'docker push {docker_image}')
            else:
                sh.docker('push', docker_image, _fg=True)
