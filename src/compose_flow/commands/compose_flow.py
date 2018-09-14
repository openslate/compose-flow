"""
    ,---,. ,--,
  ,'  .' ,--.'|
,---.'   |  | :     ,---.          .---.
|   |   .:  : '    '   ,'\\        /. ./|
:   :  : |  ' |   /   /   |    .-'-. ' |
:   |  |-'  | |  .   ; ,. :   /___/ \\: |
|   :  ;/|  | :  '   | |: :.-'.. '   ' .
|   |   .'  : |__'   | .; /___/ \\:     '
'   :  ' |  | '.'|   :    .   \\  ' .\\
|   |  | ;  :    ;\\   \\  / \\   \\   ' \\ |
|   :  \\ |  ,   /  `----'   \\   \\  |--"
|   | ,'  ---`-'             \\   \\ |
`----'                        '---"

Compose Flow - Codified workflows for Docker Compose and Swarm

This utility is built on top of Docker Compose and Swarm Mode. It establishes
conventions for publishing Images, deploying Stacks across multiple
installations (like separate dev and prod Swarms), and working with service
containers that are easily shared between team members -- and bots -- who need
to manage running services.
"""
import argparse
import logging.config
import os
import sys

from functools import lru_cache

from .subcommands import find_subcommands, set_default_subparser
from .. import settings
from ..config import DC_CONFIG_ROOT
from ..errors import CommandError, ErrorMessage
from ..utils import get_repo_name, yaml_load

PACKAGE_NAME = __name__.split('.', 1)[0].replace('_', '-')
PROJECT_NAME = get_repo_name()

CF_REMOTES_CONFIG_FILENAME = 'config.yml'
CF_REMOTES_CONFIG_PATH = os.path.expanduser(f'~/.compose/{CF_REMOTES_CONFIG_FILENAME}')


class ComposeFlow(object):
    def __init__(self, argv=None):
        self.argv = argv or sys.argv[1:]

        self.parser = self.get_argument_parser()
        self.args, self.args_remainder = self.parser.parse_known_args(self.argv)

        # the subcommand that is being run; defined in run() below
        self.subcommand = None

        if os.path.exists(DC_CONFIG_ROOT):
            os.chdir(DC_CONFIG_ROOT)

    @property
    def app_config(self) -> dict:
        """
        Returns the application config
        """
        app_config = {}

        config_path = os.environ.get('CF_REMOTES_CONFIG_PATH', CF_REMOTES_CONFIG_PATH)
        if os.path.exists(config_path):
            with open(config_path, 'r') as fh:
                app_config = yaml_load(fh)

        return app_config

    def get_argument_parser(self, doc: str=None):
        argparse.ArgumentParser.set_default_subparser = set_default_subparser

        doc = doc or __doc__

        parser = argparse.ArgumentParser(
            epilog=doc,
            formatter_class=argparse.RawDescriptionHelpFormatter
        )

        parser.add_argument('-c', '--config-name')
        parser.add_argument(
            '--dirty',
            action='store_true',
            help='allow dirty working copy for this command'
        )
        parser.add_argument('-e', '--environment')
        parser.add_argument('-l', '--loglevel', default='INFO')
        parser.add_argument('-p', '--profile')
        parser.add_argument(
            '--noop', '--dry-run',
            action='store_true', dest='dry_run',
            help='just print command, do not execute'
        )
        parser.add_argument(
            '-n', '--project-name',
            default=PROJECT_NAME,
            help=f'the project name to use, default={PROJECT_NAME}'
        )
        parser.add_argument('--version', action='store_true', help='print version and exit')

        self.subparsers = parser.add_subparsers(dest='command')

        for subcommand in find_subcommands():
            subcommand.setup_subparser(parser, self.subparsers)

        parser.set_default_subparser('help')

        return parser

    @property
    @lru_cache()
    def profile(self):
        from .subcommands.profile import Profile

        subcommand = self.subcommand

        return Profile(self, load_cf_env=subcommand.load_cf_env)

    def run(self):
        # setup the loglevel
        logging_config = settings.LOGGING
        logging_config['loggers']['compose_flow']['level'] = self.args.loglevel.upper()
        logging.config.dictConfig(logging_config)

        if self.args.version:
            import pkg_resources  # part of setuptools

            version = pkg_resources.require(PACKAGE_NAME)[0].version

            print(f'{version}')

            return

        self.subcommand = self.args.subcommand_cls(self)

        try:
            return self.subcommand.run()
        except CommandError as exc:
            self.parser.print_help()

            return f'\n{exc}'
        except ErrorMessage as exc:
            return f'\n{exc}'
