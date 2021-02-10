FROM python:3.6-stretch
MAINTAINER osslabs <code@openslatedata.com>

ARG user=swarmclient
ARG group=swarmclient
ARG uid=1000
ARG gid=1000

ENV HOME /home/${user}

RUN groupadd -g ${gid} ${group} \
 && useradd -c "Jenkins Slave user" -d "$HOME" -u ${uid} -g ${gid} -m -s /bin/bash ${user} \
 && chown -R ${user}:${group} $HOME \
 && chmod -R 770 $HOME

# Install Docker client
ENV DOCKERVERSION="19.03.14"
ENV DOCKER_SHA="0304d90f12991d4e005dbc74d0c3e1dcdda04da8"
RUN curl -fsSLO https://download.docker.com/linux/static/stable/x86_64/docker-${DOCKERVERSION}.tgz \
 && echo "$DOCKER_SHA docker-${DOCKERVERSION}.tgz" | sha1sum -c - \
 && tar xzvf docker-${DOCKERVERSION}.tgz --strip 1 \
    -C /usr/local/bin docker/docker \
 && rm docker-${DOCKERVERSION}.tgz

ARG DOCKER_GID=999
RUN groupadd -for -g ${DOCKER_GID} docker \
 && usermod -a -G docker,staff ${user}

# Install kubectl
ENV KUBE_LATEST_VERSION="v1.16.9"
ENV KUBE_SHA="32d5cf4b60d1e0c87cecf3ccb9c57011bfc5af4b"
RUN curl -L https://storage.googleapis.com/kubernetes-release/release/${KUBE_LATEST_VERSION}/bin/linux/amd64/kubectl -o /usr/local/bin/kubectl \
 && echo "$KUBE_SHA /usr/local/bin/kubectl" | sha1sum -c - \
 && chmod +x /usr/local/bin/kubectl

# Install Rancher CLI
ENV RANCHER_VERSION="v2.4.10"
ENV RANCHER_SHA="81887743affea241c5d8ca768742260ff09f762ceaf41a728048522498e433a3"
RUN curl -fsSLO https://github.com/rancher/cli/releases/download/${RANCHER_VERSION}/rancher-linux-amd64-${RANCHER_VERSION}.tar.gz \
 && echo "$RANCHER_SHA rancher-linux-amd64-${RANCHER_VERSION}.tar.gz" | sha256sum -c - \
 && tar xzvf rancher-linux-amd64-${RANCHER_VERSION}.tar.gz --strip 2 \
    -C /usr/local/bin \
 && rm rancher-linux-amd64-${RANCHER_VERSION}.tar.gz

# Install Helm client
ENV HELM_VERSION="v3.5.2"
ENV HELM_SHA="01b317c506f8b6ad60b11b1dc3f093276bb703281cb1ae01132752253ec706a2"
RUN curl -fsSLO https://get.helm.sh/helm-${HELM_VERSION}-linux-amd64.tar.gz \
 && echo "$HELM_SHA helm-${HELM_VERSION}-linux-amd64.tar.gz" | sha256sum -c - \
 && tar xzvf helm-${HELM_VERSION}-linux-amd64.tar.gz --strip 1 \
    -C /usr/local/bin \
 && chmod +x /usr/local/bin/helm \
 && rm helm-${HELM_VERSION}-linux-amd64.tar.gz

# Install compose-flow
ENV SRC_DIR /usr/local/src
WORKDIR ${SRC_DIR}

RUN mkdir ${SRC_DIR}/results

COPY files/ /
RUN chmod +x /usr/local/bin/*

RUN pip3 install pipenv

COPY Pipfile Pipfile.lock ${SRC_DIR}/

RUN pipenv install --system --dev --clear

COPY ./ ${SRC_DIR}/

RUN python setup.py install

RUN chown -R ${user}:${group} ${HOME} ${SRC_DIR}

USER ${user}

ENTRYPOINT ["/usr/local/bin/entrypoint.sh"]
