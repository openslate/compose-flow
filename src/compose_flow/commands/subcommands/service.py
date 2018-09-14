#!/usr/bin/env python3
"""
Subcommand for working with services

This subcommand provides two actions:

- list
- exec

The `list` action will list all the services for a stack when no additional
arguments are given:

```
compose-flow -e dev service list
```

When the name of a service is given, the `list` action will list all the
running containers for the specified service:

```
compose-flow -e dev service list app
```

The `exec` action will execute the given command within the specified container.
For example, the following command will launch an interactive shell in the `app`
container:

```
compose-flow -e dev service exec app /bin/bash
```
"""
import argparse
import functools
import logging
import os
import random
import sh
import shlex
import sys
import time

from .base import BaseSubcommand
from compose_flow import errors

USER = os.environ.get('USER', 'nobody')
CF_REMOTE_USER = os.environ.get('CF_REMOTE_USER', USER)


class Service(BaseSubcommand):
    @classmethod
    def fill_subparser(cls, parser, subparser):
        subparser.epilog = __doc__
        subparser.formatter_class = argparse.RawDescriptionHelpFormatter

        subparser.add_argument('--user', '-u', help='the user to become int he container')
        subparser.add_argument('--retries', type=int, default=30, help='number of times to retry')
        subparser.add_argument('--ssh', action='store_true', help='ssh to the machine, not the container')
        subparser.add_argument('--sudo', action='store_true', help='use sudo to run the docker command remotely')
        subparser.add_argument('--list', action='store_true', help='list available containers')
        subparser.add_argument('--container', type=int, default=0, help='which numbered container to select, default=0')
        subparser.add_argument('--random', action='store_true', help='pick a random matching container')
        subparser.add_argument('--service-name', help='full service name to use instead of generated')
        subparser.add_argument('action', help='The action to run')
        subparser.add_argument('service', nargs='?', help='The desired service')

    def action_exec(self):
        result = None
        for i in range(self.args.retries):
            try:
                result = self.run_service()
            except errors.NoContainer:
                time.sleep(1.0)
            else:
                break

        if not result:
            sys.exit(f'No container found for service={self.service_name}')

    def action_list(self):
        """
        Lists the stack

        if a service is given, all containers found for the given service are printed
        otherwise all the services in the stack are listed
        """
        service_name = self.service_name
        if service_name:
            print('ALL CONTAINERS:\n')

            for idx, item in enumerate(self.list_containers()):
                print('\t{}: {}'.format(idx, item))

            print(f'\nSELECTED:\n\t{self.select_container()}')
        else:
            # print(f'list services for env {self.project_name}\n')
            print(self.list_services())

    @functools.lru_cache()
    def list_containers(self, service_name: str=None):
        service_name = service_name or self.service_name

        command_split = shlex.split(
            f'docker service ps --no-trunc --filter desired-state=running {service_name}'
        )

        sh_command = getattr(sh, command_split[0])
        proc = sh_command(*command_split[1:])

        # note; because this is being cached, create a list
        # instead of a generator becuase a generator can only
        # be iterated once
        items = []

        try:
            output = proc.stdout.decode('utf8').splitlines()[1:]

            # check to see there's at least one container listed
            output[0]
        except IndexError:
            raise errors.NoContainer()
        else:
            for item in output:
                if f'{service_name}.' not in item:
                    continue

                items.append(item)

        return items

    def list_services(self):
        """
        Lists all the services for this stack
        """
        command = sh.docker('stack', 'services', self.env.project_name)

        return command.stdout.decode('utf8')

    def run_service(self):
        line = self.select_container()

        container_info = line.strip()
        container_info_split = container_info.split()

        container_hash = container_info_split[0]
        container_prefix = container_info_split[1]
        container_host = container_info_split[3]

        # print(container_info)

        if container_host.startswith('ip-'):
            container_host = container_host.replace('ip-', '').replace('-', '.')

        host_info = f'{CF_REMOTE_USER}@{container_host}'

        docker_user = ''
        if self.args.user:
              docker_user = f'--user {self.args.user} '

        command = f'ssh -t {host_info}'
        docker_command = (
            f'docker exec -t -i {docker_user}{container_prefix}.{container_hash}'
            f' {" ".join(self.workflow.args_remainder)}'
        )

        if self.args.sudo:
            docker_command = f'sudo {docker_command}'

        if not self.args.ssh:
            command = f'{command} {docker_command}'
        else:
            sys.stderr.write(f'docker_command: {docker_command}\n')

        logging.debug(f'command={command}')
        command = command.split()

        os.execvp(command[0], command)

    def select_container(self):
        containers = self.list_containers()

        if self.args.random:
            return random.choice(containers)
        else:
            return containers[self.args.container]

    @property
    def service_name(self):
        service_name = self.args.service_name
        if service_name:
            return service_name

        project_name = self.env.project_name

        service_name = self.args.service
        if not service_name:
            return

        return f'{project_name}_{self.args.service}'
