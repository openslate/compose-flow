#!/usr/bin/env python
import argparse
import base64
import os

from compose_flow import shell

parser = argparse.ArgumentParser()
parser.add_argument("root")

args = parser.parse_args()


proc = shell.execute('docker config ls --format "{{ .Name }}"', os.environ)
for config_name in proc.splitlines():
    proc = shell.execute(
        f'docker config inspect {config_name} --format "{{{{ json .Spec.Data }}}}"',
        os.environ,
    )
    buf_b64 = proc.replace('"', "")

    if not os.path.exists(args.root):
        os.makedirs(args.root)

    path = os.path.join(args.root, config_name)
    with open(path, "wb") as fh:
        fh.write(base64.b64decode(buf_b64))
