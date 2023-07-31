import base64
import logging
import re
import os

from typing import Iterable
from collections import OrderedDict

import yaml

from boltons.iterutils import remap, get_path, default_enter, default_visit
from jinja2 import Environment

from compose_flow import shell

from .errors import TagVersionError, EnvError, ProfileError

# regular expression for finding variables in docker compose files
VAR_RE = re.compile(r"\${(?P<varname>.*?)(?P<junk>[:?].*)?}")


def _get_kv(item: str) -> tuple:
    """
    Returns the item split at equal
    """
    item_split = item.split("=", 1)
    key = item_split[0]

    try:
        val = item_split[1]
    except IndexError:
        val = None

    return key, val


def get_kv(item: str, multiple: bool = False) -> Iterable[tuple]:
    """Wrapper around _get_kv() to support multiple items in the string"""
    items = [_get_kv(line) for line in item.splitlines()]

    if multiple:
        return items

    return items[0]


def get_repo_name() -> str:
    repo_name = os.path.basename(os.getcwd())

    return repo_name


def get_tag_version(default: str = None) -> str:
    """
    Returns the version of code as returned by the `tag-version` cli command

    Args:
        default: the default version if it cannot be found, `unknown` by default
        print_warning: when `tag-version` results in error, print a warning
    """
    # inject the version from tag-version command into the loaded environment
    tag_version = default or "unknown"
    try:
        proc = shell.execute("tag-version version --format docker", os.environ)
    except Exception as exc:
        error_message = str(exc)

        if "not clean" in error_message:
            tag_version = f"{tag_version}-dirty"

        raise TagVersionError(
            "Warning: tag-version failed", shell_exception=exc, tag_version=tag_version
        )
    else:
        tag_version = proc.strip()

    return tag_version


# https://gist.github.com/mahmoud/db02d16ac89fa401b968
def remerge(target_list, sourced=False):
    """Takes a list of containers (e.g., dicts) and merges them using
    boltons.iterutils.remap. Containers later in the list take
    precedence (last-wins).
    By default, returns a new, merged top-level container. With the
    *sourced* option, `remerge` expects a list of (*name*, container*)
    pairs, and will return a source map: a dictionary mapping between
    path and the name of the container it came from.
    """

    if not sourced:
        target_list = [(id(t), t) for t in target_list]

    ret = None
    source_map = {}

    def remerge_enter(path, key, value):
        new_parent, new_items = default_enter(path, key, value)
        if ret and not path and key is None:
            new_parent = ret
        try:
            cur_val = get_path(ret, path + (key,))
        except KeyError:
            pass
        else:
            # TODO: type check?
            new_parent = cur_val

        if isinstance(value, list):
            # lists are purely additive. See https://github.com/mahmoud/boltons/issues/81
            new_parent.extend(value)
            new_items = []

        return new_parent, new_items

    for t_name, target in target_list:
        if sourced:

            def remerge_visit(path, key, value):
                source_map[path + (key,)] = t_name
                return True

        else:
            remerge_visit = default_visit

        ret = remap(target, enter=remerge_enter, visit=remerge_visit)

    if not sourced:
        return ret
    return ret, source_map


def render(content: str, env: dict = None) -> str:
    """
    Renders the variables in the file
    """
    previous_idx = 0
    rendered = ""

    env = env or os.environ

    errors = []

    for x in VAR_RE.finditer(content):
        rendered += content[
            previous_idx : x.start("varname") - 2
        ]  # -2 to get rid of variable's `${`

        varname = x.group("varname")
        try:
            rendered += env[varname]
        except KeyError:
            rendered += "*** MISSING_ENVIRONMENT_VAR ***"

            errors.append(f"{varname} not found in environment")

        end = x.end("junk")
        if end == -1:
            end = x.end("varname")

        previous_idx = end + 1  # +1 to get rid of variable's `}`

    rendered += content[previous_idx:]

    logger = logging.getLogger(__name__)

    if errors:
        logger.error(rendered)
        logger.error("\n".join(errors))

        raise EnvError("Rendering error")

    return rendered


def render_jinja(content: str, env: dict = None) -> str:
    if env is None:
        env = {}

    jinja_env = Environment()
    jinja_env.filters["b64encode"] = lambda s: base64.b64encode(s.encode()).decode(
        "utf-8"
    )

    return jinja_env.from_string(content).render(env)


##
# Ordered YAML functions
# from SO at:
# https://stackoverflow.com/a/21912744
##


def yaml_load(stream, Loader=yaml.Loader, object_pairs_hook=OrderedDict):
    """
    Ordered YAML loader

    >>> ordered_load(stream, yaml.SafeLoader)
    """

    class OrderedLoader(Loader):
        pass

    def construct_mapping(loader, node):
        loader.flatten_mapping(node)
        return object_pairs_hook(loader.construct_pairs(node))

    OrderedLoader.add_constructor(
        yaml.resolver.BaseResolver.DEFAULT_MAPPING_TAG, construct_mapping
    )
    return yaml.load(stream, OrderedLoader)


def yaml_dump(data, stream=None, Dumper=yaml.Dumper, **kwds):
    """
    Ordered YAML dumper

    >>> ordered_dump(data, Dumper=yaml.SafeDumper)
    """

    class OrderedDumper(Dumper):
        pass

    def _dict_representer(dumper, data):
        return dumper.represent_mapping(
            yaml.resolver.BaseResolver.DEFAULT_MAPPING_TAG, data.items()
        )

    OrderedDumper.add_representer(OrderedDict, _dict_representer)

    # set the default_flow_style to False if not set
    kwds.setdefault("default_flow_style", False)

    return yaml.dump(data, stream, OrderedDumper, **kwds)
