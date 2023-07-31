#!/usr/bin/env python
import configparser
from setuptools import find_packages, setup

SRC_PREFIX = "src"

packages = find_packages(SRC_PREFIX)


def readme():
    with open("README.md") as f:
        return f.read()


def get_required_packages():
    """
    Returns the packages used for install_requires

    This used to pin down every package in Pipfile.lock to the version, but that, in turn, broke
    downstream projects because it was way too strict.

    Now, this simply grabs all the items listed in the `Pipfile` `[packages]` section without version
    pinning
    """
    config = configparser.ConfigParser(strict=False)
    config.read("Pipfile")

    # when the Pipfile specifies a package, constrain it to that version
    install_requires = []
    for package, version in config["packages"].items():
        full_package = package
        package_version = None

        if version[0] == "{":
            uncurled = version[1:-1]
            uncurled_split = [x.strip() for x in uncurled.split(",")]

            # find the version
            for item in uncurled_split:
                if "version" in item:
                    item_split = [x.strip() for x in item.split("=", 2)]

                    version = item_split[1][1:-1]
                    if version != "*":
                        package_version = version

                    break
        elif version != '"*"':
            package_version = version[1:-1]

        if package_version:
            full_package = f"{package}{package_version}"

        install_requires.append(full_package)

    return install_requires


setup(
    name="compose-flow",
    url="https://github.com/openslate/compose-flow",
    author="DoubleVerify",
    author_email="code@doubleverify.com",
    use_scm_version=True,
    description="codified workflows for docker compose",
    license_files=("LICENSE",),
    long_description=readme(),
    long_description_content_type="text/markdown",
    package_dir={"": "src"},
    packages=packages,
    entry_points={
        "console_scripts": ["compose-flow = compose_flow.entrypoints:compose_flow"]
    },
    install_requires=get_required_packages(),
)
