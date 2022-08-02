#!/usr/local/bin/python

import json
import socket
import sys

import asfgit.cfg as cfg
import asfgit.git as git
import asfgit.log as log
import asfgit.util as util
import subprocess, os, time

locations = ['/x1/repos/asf/', '/x1/repos/private']

def main():
    ghurl = f"git@github:apache/{cfg.repo_name}.git"
    for loc in locations:
        filepath = os.path.join(loc, f'{cfg.repo_name}.git')
        if os.path.exists(filepath):
            break
        else:
            filepath = None
    if filepath:
        os.chdir(filepath)
        try:
            for ref in git.stream_refs(sys.stdin):
                if ref.is_rewrite():
                    print(f"Syncing {ref.name} (FORCED)...")
                    subprocess.check_output(
                        [
                            "git",
                            "push",
                            "-f",
                            ghurl,
                            f"{ref.newsha}:{ref.name}",
                        ]
                    )

                else:
                    print(f"Syncing {ref.name}...")
                    subprocess.check_output(["git", "push", ghurl, f"{ref.newsha}:{ref.name}"])
        except subprocess.CalledProcessError as err:
            what = err.output
            if type(what) is bytes:
                what = what.decode('utf-8')
            util.abort(f"Could not sync with GitHub: {what}")
    else:
        util.abort("Could not sync with GitHub: Could not determine file-path for repository!")
