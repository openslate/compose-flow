# Compose Flow

This utility is built on top of [Docker Compose](https://docs.docker.com/compose/) and [Swarm Mode](https://docs.docker.com/engine/swarm/).  It establishes workflow conventions that are easily shared between team members -- and butlers -- who need to manage and deploy services, including:

- managing [Stacks](https://docs.docker.com/get-started/part5/#prerequisites) across multiple Swarms (e.g. separate dev and prod Swarms)
- connecting to and working with service containers
- building and publishing images
- sharing service configuration between team members


## Installation

```
pip install compose-flow
```


## Compose-Flow configuration

Create the file `~/.compose/config.yml` with the following sections.

### Build

```yaml
build:
  # the image prefix can be your Docker Hub username or a private registry address
  image_prefix: myprivateregistry.com
```

### Remotes

```yaml
remotes:
  local:
    backend: swarm
  test:
    backend: rancher
    rancher:
      project: Ops
      cluster: prod
  dev:
    backend: rancher
  prod:
    backend: rancher
```

With this in place you're ready to go onto your project setup.


# A basic example

This is the most basic file to get started.

Place this at `compose/compose-flow.yml` in your project directory:

```
profiles:
  local:
    - docker-compose.yml
```

Alongside it, place the file `compose/docker-compose.yml`:

```
version: '3.7'
services:
  app:
    build: ..
    image: ${DOCKER_IMAGE}
```

For building, run: `compose-flow build`.

For publishing: `compose-flow publish`.

For deploying as configured above: `compose-flow -e local deploy`.

More information at [docs/advanced.md](docs/advanced.md)


## Compose Flow Development

First you setup some default evn vars
```compose-flow -e local env edit```

```
CF_ENV=local
CF_ENV_NAME=compose-flow
CF_PROJECT=compose-flow
```

Then to build the container
```compose-flow -e local compose build```

Then to shell into the container
```compose-flow -e local compose run --rm app /bin/bash```


Testing can then be ran via pytest 
```compose-flow -e local compose run --rm app /bin/bash -c pytest```