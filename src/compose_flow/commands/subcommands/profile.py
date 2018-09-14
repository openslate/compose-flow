"""
Profile subcommand
"""
import copy
import os
import tempfile

from .base import BaseSubcommand

from compose_flow.compose import get_overlay_filenames
from compose_flow.config import get_config
from compose_flow.errors import EnvError, NoSuchConfig, NoSuchProfile, ProfileError
from compose_flow.utils import remerge, render, yaml_dump, yaml_load

COPY_ENV_VAR = 'CF_COPY_ENV_FROM'

# keep track of written profiles in order to prevent writing them twice
WRITTEN_PROFILES = []


def get_kv(item: str) -> tuple:
    """
    Returns the item split at equal
    """
    item_split = item.split('=', 1)
    key = item_split[0]

    try:
        val = item_split[1]
    except IndexError:
        val = None

    return key, val


def listify_kv(d: dict) -> list:
    """
    Returns an equal-delimited list of the dictionary's key/value pairs

    When the value is null the equal is not appended
    """
    return [f'{k}={v}' if v else k for k, v in d.items()]


class Profile(BaseSubcommand):
    """
    Subcommand for managing profiles
    """
    @property
    def filename(self) -> str:
        """
        Returns the filename for this profile
        """
        return f'compose-flow-{self.args.profile}.yml'

    @classmethod
    def fill_subparser(cls, parser, subparser):
        subparser.add_argument('action')

    @property
    def data(self):
        compose_content = self.load()

        return yaml_load(compose_content)

    def cat(self):
        """
        Prints the loaded compose file to stdout
        """
        print(self.load())

    def check(self):
        """
        Checks the profile against some rules
        """
        env_data = self.env.data

        errors = []
        for name, service_data in self.data['services'].items():
            for item in service_data.get('environment', []):
                # when a variable has an equal sign, it is setting
                # the value, so don't check the environment for this variable
                if '=' in item:
                    continue

                if item not in env_data:
                    errors.append(f'{item} not found in environment')

        if errors:
            raise ProfileError('\n'.join(errors))

    def cf_config_expand(self, data):
        expand_config = data['compose_flow']['expand']
        for service_name, config in expand_config.items():
            base_service = data['services'].pop(service_name)
            replicas = base_service['deploy']['replicas']

            increment_config = expand_config[service_name].get('increment')

            for idx in range(replicas):
                _service_name = f'{service_name}{idx+1}'
                _service = copy.deepcopy(base_service)

                _service['deploy'].pop('replicas')

                if increment_config:
                    for _increment_config_name, _increment_config_data in increment_config.items():
                        fn_name = f'cf_config_expand_increment_{_increment_config_name}'
                        _service = getattr(self, fn_name)(_increment_config_data, idx, _service)

                data['services'][_service_name] = _service

    def cf_config_expand_increment_env(self, increment_config: dict, item_index: int, service: dict) -> dict:
        if not isinstance(service['environment'], list):
            raise NotImplementedError('environment dictionary is not supported, use list format')

        new_env = []
        for item in service['environment']:
            if '=' not in item:
                new_env.append(item)

                continue

            k, v = item.split('=', 1)
            if k not in increment_config:
                new_env.append(item)

                continue

            v_int = int(v)

            new_env.append(f'{k}={v_int+item_index}')

        service['environment'] = new_env

        return service

    def cf_config_expand_increment_ports(self, increment_config: dict, item_index: int, service: dict) -> dict:
        new_ports = []

        for item in service['ports']:
            source, dest = item.split(':')
            source_i = int(source)
            dest_i = int(dest)

            if increment_config.get('source_port', False):
                source_i += item_index

            if increment_config.get('destination_port', False):
                dest_i += item_index

            new_ports.append(f'{source_i}:{dest_i}')

        service['ports'] = new_ports

        return service

    def _check_cf_config(self, data):
        """
        Expands out any services that should be duplicated
        """
        cf_config_sections = list(data.get('compose_flow', {}).keys())
        for item in cf_config_sections:
            fn_name = f'cf_config_{item}'

            getattr(self, fn_name)(data)

        return data

    def _copy_environment(self, data):
        """
        Processes CF_COPY_ENV_FROM environment entries
        """
        environments = {}

        # first get the env from each service
        for service_name, service_data in data['services'].items():
            environment = service_data.get('environment')
            if environment:
                _env = {}

                for item in environment:
                    k, v = get_kv(item)

                    _env[k] = v

                environments[service_name] = _env

        # go through each service environment and apply any copies found
        for service_name, service_data in data['services'].items():
            environment = service_data.get('environment')
            if not environment:
                continue

            new_env = {}
            for item in environment:
                key, val = get_kv(item)
                new_env[key] = val

                if not item.startswith(COPY_ENV_VAR):
                    continue

                _env = environments.get(val)
                if not _env:
                    raise EnvError(f'Unable to find val={val} to copy into service_name={service_name}')

                new_env.update(_env)

            service_data['environment'] = listify_kv(new_env)

        return data

    def get_profile_compose_file(self, profile):
        """
        Processes the profile to generate the compose file
        """
        self.update_runtime_environment()

        filenames = get_overlay_filenames(profile)

        # merge multiple files together so that deploying stacks works
        # https://github.com/moby/moby/issues/30127
        if len(filenames) > 1:
            yaml_contents = []

            for item in filenames:
                with open(item, 'r') as fh:
                    yaml_contents.append(yaml_load(fh))

            merged = remerge(yaml_contents)
            content = yaml_dump(merged)
        else:
            try:
                with open(filenames[0], 'r') as fh:
                    content = fh.read()
            except FileNotFoundError:
                content = ''

        # perform transformations on the compiled profile
        if content:
            data = yaml_load(content)

            # check if the environment needs to be copied from another service
            data = self._copy_environment(data)

            # see if any services need to be expanded out
            data = self._check_cf_config(data)

            # drop the compose_flow section if it exists
            data.pop('compose_flow', None)

            content = yaml_dump(data)

        fh = tempfile.TemporaryFile(mode='w+')

        # render the file
        try:
            rendered = render(content)
        except EnvError as exc:
            if not self.workflow.subcommand.is_missing_profile_okay(exc):
                raise

            return fh

        fh.write(rendered)
        fh.flush()

        fh.seek(0, 0)

        return fh

    def load(self) -> str:
        """
        Loads the compose file that is generated from all the items listed in the profile
        """
        fh = self.get_profile_compose_file(self.profile_files)

        return fh.read()

    @property
    def profile_files(self) -> dict:
        """
        Returns the profile data found in the dc.yml file
        """
        config = get_config()
        if not config:
            return {}

        profile_name = self.args.profile

        # when there is no profile name, return just docker-compose.yml
        if profile_name is None:
            return ['docker-compose.yml']

        try:
            profile = config['profiles'][profile_name]
        except KeyError:
            raise NoSuchProfile(f'profile={profile_name}')

        return profile

    def write(self) -> None:
        """
        Writes the loaded compose file to disk
        """
        # do not write profiles more than once per execution
        if self.filename in WRITTEN_PROFILES:
            return

        with open(self.filename, 'w') as fh:
            fh.write(self.load())

        WRITTEN_PROFILES.append(self.filename)
