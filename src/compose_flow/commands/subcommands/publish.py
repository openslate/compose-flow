import logging
import re

import semantic_version

from functools import lru_cache

from .base import BaseSubcommand


class Publish(BaseSubcommand):
    """
    Subcommand for building and pushing Docker images
    """

    rw_env = True
    remote_action = True
    update_version_env_vars = True

    def auto_tag(self):

        built_images = self.get_built_docker_images()
        new_tags = self.get_auto_tag_docker_images(built_images)

        for docker_image, auto_tag_images in new_tags.items():
            for auto_tag in auto_tag_images:
                # tag all our images
                self.execute(f'docker tag {docker_image} {auto_tag}', _fg=True)

    def build(self):
        compose = self.compose

        compose.handle(extra_args=['build'])

    @property
    @lru_cache()
    def compose(self):
        """
        Returns a Compose subcommand
        """
        from .compose import Compose

        return Compose(self.workflow)

    def do_validate_profile(self):
        return False

    @classmethod
    def fill_subparser(cls, parser, subparser) -> None:
        subparser.add_argument(
            '--skip-auto-tag',
            action='store_true',
            help='do not publish major, minor, and latest tags for images built by compose-flow',
        )

    def get_auto_tag_docker_images(self, built_images: list) -> dict:
        """
        Returns a dict of original docker image names pointing to list of new tags to push.
        """

        # if we received a skip auto tags flag, simply return the images without any tags
        if self.workflow.args.skip_auto_tag:
            return dict([(image, []) for image in built_images])

        new_tags = {}

        for image in built_images:
            auto_tags = []
            image_name = image.split(':')[0]

            tag = image.split(':')[-1]

            semver = semantic_version.Version(tag)

            # only build major and minor if this is a clean patch or minor release
            if not (semver.prerelease and semver.build):
                auto_tags.append(f'{image_name}:{semver.major}')

                auto_tags.append(f'{image_name}:{semver.major}.{semver.minor}')

            auto_tags.append(':'.join([image_name, 'latest']))

            new_tags[image] = auto_tags

        return new_tags

    def get_built_docker_images(self) -> list:
        """
        Returns a list of docker images built in the compose file
        """
        docker_images = set()

        profile = self.workflow.profile
        for service_data in profile.data['services'].values():
            if service_data.get('build'):
                docker_images.add(service_data.get('image'))

        return list(docker_images)

    def get_docker_images_for_push(self):
        built_images = self.get_built_docker_images()
        new_tags = self.get_auto_tag_docker_images(built_images)

        push_tags = []

        for k, v in new_tags.items():
            push_tags.append(k)
            push_tags += v

        return push_tags

    def handle(self):
        self.build()

        self.auto_tag()

        self.push()

    def is_missing_env_arg_okay(self):
        return True

    @property
    def logger(self):
        return logging.getLogger(f'{__name__}.{self.__class__.__name__}')

    def push(self):
        docker_images = self.get_docker_images_for_push()

        for docker_image in docker_images:
            # push up all images along with major, minor, latest by default
            if self.workflow.args.dry_run:
                self.logger.info(f'docker push {docker_image}')
            else:
                self.execute(f'docker push {docker_image}', _fg=True)
