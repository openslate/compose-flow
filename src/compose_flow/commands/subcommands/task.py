"""
Task subcommand
"""
import logging
import shlex

from .base import BaseSubcommand

from compose_flow.config import get_config
from compose_flow.errors import CommandError


class Task(BaseSubcommand):
    @classmethod
    def fill_subparser(self, parser, subparser):
        subparser.add_argument('name', help='the task name to process')

    def handle(self):
        config = get_config()

        task_name = self.args.name
        try:
            task = config['tasks'][task_name]
        except KeyError:
            raise CommandError('task name={task_name} not found')

        command = task['command']
        command_split = shlex.split(command)

        if command_split[0] != 'compose-flow':
            raise NotImplementedError('tasks that are not compose-flow are not yet supported')

        subcommand_name = command_split[1]
        subcommand = self.get_subcommand(subcommand_name)

        subcommand_args = command_split[2:]

        remainder = self.workflow.args_remainder
        if remainder:
            subcommand_args.extend(remainder)

        subcommand.run(subcommand_args)

    def is_dirty_working_copy_okay(self, exc: Exception) -> bool:
        dirty_working_copy_okay = super().is_dirty_working_copy_okay(exc)

        if not dirty_working_copy_okay and self.workflow.args.environment in ('local',):
            self.logger.warning((
                '\n\n'
                'WARNING: the local environment does not allow a dirty working copy by default.'
                '\n'
                'in your compose-flow.yml set `options -> local -> dirty_working_copy_okay` to true'
                '\n\n'
            ))

        return dirty_working_copy_okay

    @property
    def logger(self):
        return logging.getLogger(f'{__name__}.{self.__class__.__name__}')
