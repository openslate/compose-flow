"""
Connect to a remote docker swarm
"""
import os
import re
import sys

import sh

from .base import BaseSubcommand

from compose_flow import errors
from compose_flow.errors import EnvError, ErrorMessage

UNIX_PREFIX = 'unix://'
UNIX_REMOTE_HOST_RE = re.compile(UNIX_PREFIX + r'(?P<socket>.*)')


class Remote(BaseSubcommand):
    """
    Subcommand for connecting to a remote docker swarm
    """
    def __init__(self, *args, **kwargs):
        self._host = kwargs.pop('host', None)

        super().__init__(*args, **kwargs)

    def close(self, pids=None, do_print=True):
        try:
            pids = pids or list(self.get_remote_ssh_pids())
        except EnvError:
            pass
        else:
            if do_print:
                pids_s = ", ".join([f'{x}' for x in pids])
                print(f'closing pids {pids_s}', file=sys.stderr)

            for pid in pids:
                sh.kill(pid)

        self.remove_socket()

        if do_print:
            self.print_eval_hint()
            print(f'unset DOCKER_HOST')

    def connect(self):
        self.make_connection()

        if remote_host != self.socket_path:
            self.print_eval_hint()

            print(f'export DOCKER_HOST={self.docker_host}')

    @property
    def docker_host(self):
        socket_path = self.socket_path
        if socket_path:
            return f'{UNIX_PREFIX}{socket_path}'

    @classmethod
    def fill_subparser(cls, parser, subparser):
        subparser.add_argument('action')
        subparser.add_argument('--host')

    def get_remote_host(self):
        return self.docker_host or os.environ.get('DOCKER_HOST')

    def get_remote_ssh_pids(self):
        socket = self.get_socket()
        pgrep_search = f'ssh -Nf -L {socket}'

        try:
            proc = sh.pgrep('-f', pgrep_search)
        except sh.ErrorReturnCode_1:
            pass
        else:
            for item in proc.stdout.decode('utf8').strip().splitlines():
                yield int(item)

    def get_socket(self):
        remote_host = self.get_remote_host()
        if not remote_host:
            raise EnvError('DOCKER_HOST not defined')

        matches = UNIX_REMOTE_HOST_RE.match(remote_host)
        if not matches:
            raise ErrorMessage(f'cannot parse remote_host={remote_host}')

        return matches.group('socket')

    @property
    def host(self):
        if self._host is not None:
            return self._host

        try:
            self._host = self.args.host
        except AttributeError:
            # when called by another command, the arg may not exist
            pass

        if not self._host:
            data = self.workflow.app_config
            environment = self.args.environment

            try:
                self._host = data['remotes'][self.args.environment]['ssh']
            except KeyError:
                # it's perfectly fine to not have a remote config for an environment
                pass

        return self._host

    def is_env_error_okay(self, exc):
        return True

    def is_host_defined(self):
        return self.host is not None

    def is_missing_config_okay(self, exc):
        return self.is_host_defined()

    def is_missing_env_arg_okay(self):
        return self.is_host_defined()

    def is_missing_profile_okay(self, exc):
        return True

    def is_not_connected_okay(self, exc):
        if self.workflow.args.action in ('connect',):
            return True

        return super().is_not_connected_okay(exc)

    def is_write_profile_error_okay(self, exc):
        return True

    def make_connection(self, use_existing=False):
        try:
            pids = list(self.get_remote_ssh_pids())
        except (EnvError, ErrorMessage):
            pids = []

        try:
            remote_host = self.get_remote_host()
        except EnvError:
            remote_host = None

        try:
            if self.status(docker_host=self.docker_host, do_print=False):
                raise errors.AlreadyConnected(f'already connected to {remote_host}')
        except EnvError:
            pass

        if pids:
            self.close(do_print=False)

        host = self.host
        if not host:
            raise errors.RemoteUndefined('Error: Remote host not given')

        socket_path = self.socket_path

        self.remove_socket()

        self.close(do_print=False)

        sh.ssh('-Nf', '-L', f'{socket_path}:/var/run/docker.sock', host)

    def print_eval_hint(self):
        print(
            'copy and paste the commands below or run this command wrapped in an eval statement:\n',
            file=sys.stderr
        )

    def remove_socket(self):
        socket_path = self.socket_path
        if os.path.exists(socket_path):
            os.remove(socket_path)

    @property
    def socket_path(self):
        host = self.host
        if self.host:
            return f'/tmp/compose-flow-{host}.sock'

    def status(self, docker_host=None, do_print=True):
        pids = []
        status = False

        docker_host = docker_host or self.get_remote_host()
        try:
            pids = list(self.get_remote_ssh_pids())
        except ErrorMessage:
            pass

        # we are connected if we get PIDs back
        connected = len(pids) > 0

        if docker_host and connected:
            status = True

            message = f'connected to docker_host {docker_host}, ssh pid {pids}'
        elif docker_host:
            message = f'environment set to {docker_host}, but no ssh connection found'
        elif pids:
            pids_s = ", ".join([f'{x}' for x in pids])
            message = f'ssh connection found at pids {pids_s}, but environment not setup'
        else:
            message = 'Not connected'

        if message and do_print:
            print(message)

        return status
