import logging
import os

from abc import ABC, abstractclassmethod

from compose_flow import errors
from compose_flow.config import get_config
from compose_flow.errors import CommandError, EnvError, NoSuchConfig, \
    NoSuchProfile, NotConnected, ProfileError, TagVersionError


class BaseSubcommand(ABC):
    """
    Parent class for any subcommand class
    """
    dirty_working_copy_okay = False

    # whether this subcommand should connect to the remote host
    remote_action = True

    # whether the env should be in read/write mode
    rw_env = False

    def __init__(self, workflow, load_cf_env=True):
        self.workflow = workflow

        self.load_cf_env = load_cf_env

    @property
    def logger(self):
        return logging.getLogger(f'{__name__}.{self.__class__.__name__}')

    @property
    def args(self):
        return self.workflow.args

    def _check_args(self):
        """
        Checks and transforms the command line arguments
        """
        args = self.workflow.args

        if None in (args.environment,):
            if not self.workflow.subcommand.is_missing_env_arg_okay():
                raise CommandError('Error: environment is required')

        args.profile = args.profile or args.environment

    def get_subcommand(self, name:str) -> object:
        """
        Returns the requested subcommand class by name
        """
        from . import get_subcommand_class

        subcommand_cls = get_subcommand_class(name)

        return subcommand_cls(self.workflow)

    @property
    def env(self):
        """
        Returns an Env instance
        """
        # avoid circular import
        from .env import Env

        return Env(self.workflow)

    @property
    def env_name(self):
        args = self.workflow.args

        return args.environment

    @abstractclassmethod
    def fill_subparser(cls, parser, subparser):
        """
        Stub for adding arguments to this subcommand's subparser
        """

    def handle(self):
        return self.handle_action()

    def handle_action(self):
        action = self.workflow.args.action

        action_fn = getattr(self, f'action_{action}', None)
        if not action_fn:
            action_fn = getattr(self, action, None)

        if action_fn:
            return action_fn()
        else:
            self.print_subcommand_help(self.__doc__, error=f'unknown action={action}')

    def is_dirty_working_copy_okay(self, exc: Exception) -> bool:
        """
        Checks to see if the project's compose-flow.yml allows for the env to use a dirty working copy

        To configure an environment to allow a dirty working copy, add the following to the compose-flow.yml

        ```
        options:
          env_name:
            dirty_working_copy_okay: true
        ```

        This defaults to False
        """
        config = get_config() or {}
        env = self.workflow.args.environment

        dirty_working_copy_okay = self.workflow.args.dirty or config.get('options', {}).get(env, {}).get(
            'dirty_working_copy_okay', self.dirty_working_copy_okay
        )

        return dirty_working_copy_okay

    def is_env_error_okay(self, exc):
        return False

    def is_env_runtime_error_okay(self):
        return False

    def is_missing_config_okay(self, exc):
        return False

    def is_missing_env_arg_okay(self):
        return False

    def is_missing_profile_okay(self, exc):
        return False

    def is_not_connected_okay(self, exc):
        return False

    def is_write_profile_error_okay(self, exc):
        return False

    def print_subcommand_help(self, doc, error=None):
        print(doc.lstrip())

        self.workflow.parser.print_help()

        if error:
            return f'\nError: {error}'

    @property
    def project_name(self):
        args = self.workflow.args

        return f'{self.env_name}-{args.project_name}'

    def run(self, *args, **kwargs):
        subcommand = self.workflow.subcommand

        try:
            if subcommand.remote_action:
                self.logger.debug('setup remote')
                self._setup_remote()
            else:
                self.logger.debug('work locally')
        except errors.NotConnected as exc:
            if not self.is_not_connected_okay(exc):
                raise

        self._check_args()

        try:
            self._write_profile()
        except (EnvError, NotConnected, ProfileError, TagVersionError) as exc:
            if not self.is_write_profile_error_okay(exc):
                raise
        except NoSuchConfig as exc:
            if not self.is_missing_config_okay(exc):
                raise
        except NoSuchProfile as exc:
            if not self.is_missing_profile_okay(exc):
                raise

        return self.handle(*args, **kwargs)

    def _setup_remote(self):
        """
        Sets DOCKER_HOST based on the environment
        """
        # avoid circular import
        from .remote import Remote

        remote = Remote(self.workflow)

        try:
            remote.make_connection(use_existing=True)
        except (errors.AlreadyConnected, errors.RemoteUndefined):
            pass
        except errors.NotConnected as exc:
            if not self.is_not_connected_okay(exc):
                raise

        docker_host = remote.docker_host
        if docker_host:
            os.environ.update({
                'DOCKER_HOST': docker_host,
            })

    @classmethod
    def setup_subparser(cls, parser, subparsers):
        name = cls.__name__.lower()
        aliases = getattr(cls, 'aliases', [])

        subparser = subparsers.add_parser(name, aliases=aliases)
        subparser.set_defaults(subcommand_cls=cls)

        cls.fill_subparser(parser, subparser)

    def update_runtime_environment(self, **kwargs):
        """
        Updates os.environ with the current environment
        """
        try:
            runtime_env = self.env.get_data()
        except NoSuchConfig as exc:
            if not self.workflow.subcommand.is_env_error_okay(exc):
                raise
        else:
            os.environ.update(runtime_env)

    def _write_profile(self):
        """
        Writes a compiled compose file using the info in the yml file
        """
        self.workflow.profile.write()
