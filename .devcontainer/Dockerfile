# syntax=docker/dockerfile:1

ARG VARIANT=3.12
FROM mcr.microsoft.com/devcontainers/python:${VARIANT}


USER root
RUN apt-get update && apt-get install -y --no-install-recommends \
    curl git make bash ca-certificates unzip \
    && rm -rf /var/lib/apt/lists/*

RUN ACT_VERSION=$(curl -s https://api.github.com/repos/nektos/act/releases/latest | grep -m1 tag_name | cut -d '"' -f 4) \
    && curl -L -o /tmp/act.tgz https://github.com/nektos/act/releases/download/${ACT_VERSION}/act_Linux_x86_64.tar.gz \
    && tar -xzf /tmp/act.tgz -C /usr/local/bin act && rm /tmp/act.tgz

WORKDIR /workspaces/bakalari-ha

USER vscode
