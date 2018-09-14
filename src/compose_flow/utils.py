import re
import os
import sys
import yaml

from collections import OrderedDict

import sh

from boltons.iterutils import remap, get_path, default_enter, default_visit

from .errors import EnvError, ProfileError

# regular expression for finding variables in docker compose files
VAR_RE = re.compile(r'\${(?P<varname>.*?)(?P<junk>[:?].*)?}')


def get_repo_name() -> str:
    repo_name = os.path.basename(os.getcwd())

    return repo_name


def get_tag_version() -> str:
    """
    Returns the version of code as returned by the `tag-version` cli command
    """
    # inject the version from tag-version command into the loaded environment
    tag_version = 'unknown'
    try:
        tag_version_command = getattr(sh, 'tag-version')
    except Exception as exc:
        print(f'Warning: unable to find tag-version ({exc})\n', file=sys.stderr)
    else:
        tag_version = tag_version_command().stdout.decode('utf8').strip()

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


def render(content: str, env: dict=None) -> str:
    """
    Renders the variables in the file
    """
    previous_idx = 0
    rendered = ''

    env = env or os.environ

    for x in VAR_RE.finditer(content):
        rendered += content[previous_idx:x.start('varname')-2]  # -2 to get rid of variable's `${`

        varname = x.group('varname')
        try:
            rendered += env[varname]
        except KeyError:
            raise EnvError(f'Error: varname={varname} not in environment; cannot render')

        end = x.end('junk')
        if end == -1:
            end = x.end('varname')

        previous_idx = end + 1  # +1 to get rid of variable's `}`

    rendered += content[previous_idx:]

    return rendered


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
        yaml.resolver.BaseResolver.DEFAULT_MAPPING_TAG,
        construct_mapping)
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
            yaml.resolver.BaseResolver.DEFAULT_MAPPING_TAG,
            data.items())
    OrderedDumper.add_representer(OrderedDict, _dict_representer)

    # set the default_flow_style to False if not set
    kwds.setdefault('default_flow_style', False)

    return yaml.dump(data, stream, OrderedDumper, **kwds)
