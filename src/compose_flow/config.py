import os
import pathlib
import typing

from functools import lru_cache

from influxstats.logging import get_logger

from compose_flow.utils import remerge, yaml_dump, yaml_load

if typing.TYPE_CHECKING:
    from .commands.workflow import Workflow

DictNone = typing.Union[dict, None]

DEFAULT_DC_CONFIG_FILE = pathlib.Path("compose") / "compose-flow.yml"

# check to see if an overlay file is provided in the environment
DC_CONFIG_PATH = os.environ.get("DC_CONFIG_FILE", DEFAULT_DC_CONFIG_FILE)

DC_CONFIG_ROOT, DC_CONFIG_FILE = os.path.split(DC_CONFIG_PATH)


# noinspection PyUnusedLocal
def check_config(workflow: "Workflow", data: dict) -> dict:
    if not data:
        return data

    # check for a compose_flow section
    compose_flow = data.get("compose_flow", None)
    if not compose_flow:
        return data

    extends = compose_flow.get("config", {}).get("extends")
    if not extends:
        return data

    configs = []
    for item in extends:
        with open(item) as fh:
            configs.append(yaml_load(fh))

    # append the config that was read in to the configs list
    configs.append(data)

    # mash them together
    data = remerge(configs)

    return data


def get_base_config_name(workflow: "Workflow") -> str:
    """Returns the config name without the environment prefix

    Args:
        workflow: The running workflow
    """
    logger = get_logger()

    base_config_name = workflow.config_name

    # NOTE: use environment_name instead of environment because
    # using the latter may cause a recursive loop
    environment_prefix = f"{workflow.environment_name}-"

    if base_config_name.startswith(environment_prefix):
        base_config_name = base_config_name.split(environment_prefix, 1)[-1]

    logger.debug(f"base_config_name={base_config_name}")

    return base_config_name


@lru_cache()
def get_config(workflow: "Workflow") -> DictNone:
    """Returns the compose-flow project config file

    By default, this will check for a compose-flow file in compose/ with the same
    name as the project name, e.g. compose/compose-flow.my-project.yml.  when a file with the
    same name as the project is not found, the default file compose/compose-flow.yml
    is used.

    When `-f` is provided on the command line, that file is the only file searched,
    and an exception will be raised when it is not found.
    """
    data = read_project_config(workflow) or {}

    data = check_config(workflow, data)

    return data


def read_project_config(workflow: "Workflow") -> dict:
    """Reads the project config from the filesystem"""
    data = {}

    logger = get_logger()

    compose_flow_filename = workflow.args.compose_flow_filename

    if compose_flow_filename:
        paths = [compose_flow_filename]
    else:
        config_name_config_file = f"compose-flow.{workflow.config_basename}.yml"
        project_name_config_file = f"compose-flow.{workflow.project_name}.yml"

        paths = [config_name_config_file, project_name_config_file, DC_CONFIG_PATH]

    for item in paths:
        filename = os.path.basename(item)

        logger.debug(f"looking for {filename}")

        if os.path.exists(filename):
            with open(filename, "r") as fh:
                data = yaml_load(fh)

                break
    else:
        logger.warning(f"compose-flow config not found; tried {paths} in {os.getcwd()}")

    outfile = f"compose-flow-{workflow.config_name}-config.yml"
    with open(outfile, "w") as fh:
        fh.write(yaml_dump(data))

    return data
