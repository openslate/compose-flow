import base64
import json
import os

from contextlib import contextmanager
from typing import Iterable

from compose_flow import shell

from .errors import DockerError, NoSuchConfig, NotConnected


@contextmanager
def json_formatter(command: str) -> str:
    """
    Yields the docker command with the JSON formatter

    Args:
        command: docker command

    Returns:
        Augmented docker command
    """
    yield f'{command} --format "{{{{ json . }}}}"'


def get_configs() -> list:
    """
    Returns a list of config names found in the swarm
    """
    output = get_docker_output('docker config ls --format "{{ .Name }}"', os.environ)

    return output.splitlines()


def get_config(name: str) -> str:
    """
    Returns the content of the config in the swarm
    """
    try:
        data = list(get_docker_json(f"docker config inspect {name}", os.environ))[0]
    except DockerError as exc:
        exc_s = str(exc).lower()

        # if the config does not exist in docker, raise NoSuchConfig
        if "no such config" in exc_s:
            raise NoSuchConfig(f"config name={name} not found")

        raise

    config_data = data[0]["Spec"]["Data"]

    return base64.b64decode(config_data).decode("utf8")


def get_nodes() -> Iterable:
    """
    Returns a list of swarm nodes
    """
    with json_formatter("docker node ls") as json_command:
        return get_docker_json(json_command, os.environ, jsonl=True)


def get_service_config(name: str) -> dict:
    """
    Returns `docker service inspect` as a data object

    Args:
        name: the name of the service

    Returns:
        dict
    """
    with json_formatter(f"docker service inspect {name}") as command:
        data = list(get_docker_json(command, os.environ))

        return data


def get_services() -> Iterable:
    """
    Returns an iterable of service objects
    """
    with json_formatter("docker service ls") as json_command:
        return get_docker_json(json_command, os.environ, jsonl=True)


def load_config(name: str, path: str) -> None:
    """
    Loads config into swarm
    """
    configs = get_configs()
    if name in configs:
        remove_config(name)

    shell.execute(f"docker config create {name} {path}", os.environ)


def remove_config(name: str) -> None:
    """
    Removes a config from the swarm
    """
    shell.execute(f"docker config rm {name}", os.environ)


def get_docker_json(command: str, env: dict, jsonl: bool = False) -> [dict, Iterable]:
    """
    Returns docker output as a JSON object

    Args:
        command: the docker command to run
        env: the environment to run the command with
        jsonl: whether to interpret the output as a JSON doc per line

    Returns:
        dict
    """
    content = get_docker_output(command, env)

    if jsonl:
        for line in content.splitlines():
            yield json.loads(line)
    else:
        yield json.loads(content)


def get_docker_output(command: str, env: dict) -> str:
    """
    Returns docker stdout as a string

    Args:
        command: the docker command to run
        env: the environment to run the command under

    Returns:
        str
    """
    try:
        proc = shell.execute(command, env)
    except shell.ErrorReturnCode_1 as exc:
        exc_s = f"{exc}".lower()
        if "cannot connect to the docker daemon" in exc_s:
            raise NotConnected()

        raise DockerError(exc)

    return proc.stdout.decode("utf8")
