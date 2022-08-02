#!/usr/local/bin/python

import json
import sys
import time
import requests
import yaml
import subprocess
import os

import asfgit.cfg as cfg
import asfgit.git as git
import asfgit.log as log

def has_publishing_via_asfyaml(refname):
    """ Figure out if this branch has a .asf.yaml file with publishing enabled.
        If so, tell gitwcsub to ignore publishing it, so stageD can take over """
    try:
        FNULL = open(os.devnull, 'w')
        ydata = subprocess.check_output(
            ("/usr/bin/git", "show", f"{refname}:.asf.yaml"), stderr=FNULL
        )

    except:
        ydata = ""
    if not ydata:
        return False
    try:
        config = yaml.safe_load(ydata)
    except yaml.YAMLError as e:
        # On broken yaml, fall back to simple text detection
        # We're playing safe, as we don't want a broken .asf.yaml to make gitwcsub take over again
        return "publish:" in ydata
    return 'publish' in config if type(config) is dict else False

def main():
    for ref in git.stream_refs(sys.stdin):
        rname = ref.name if hasattr(ref, 'name') else "unknown"
        via_asfyaml = has_publishing_via_asfyaml(rname)
        send_json(
            {
                "repository": "git",
                "server": "gitbox",
                "project": cfg.repo_name,
                "ref": rname,
                "type": "tag" if ref.is_tag() else "branch",
                "from": None if ref.created() else ref.oldsha,
                "to": None if ref.deleted() else ref.newsha,
                "action": "created"
                if ref.created()
                else "deleted"
                if ref.deleted()
                else "updated",
                "actor": cfg.committer,
                "date": time.strftime("%Y-%m-%d %H:%M:%S", time.gmtime()),
            },
            "push",
        )

        if ref.is_tag():
            send_json(
                {
                    "repository": "git",
                    "server": "gitbox",
                    "project": cfg.repo_name,
                    "ref": rname,
                    "hash": "null",
                    "sha": "null",
                    "date": time.strftime("%Y-%m-%d %H:%M:%S", time.gmtime()),
                    "authored": time.strftime(
                        "%Y-%m-%d %H:%M:%S", time.gmtime()
                    ),
                    "author": cfg.committer,
                    "email": cfg.remote_user,
                    "committer": cfg.committer,
                    "commited": time.strftime(
                        "%Y-%m-%d %H:%M:%S", time.gmtime()
                    ),
                    "ref_names": "",
                    "subject": rname,
                    "log": f"Create {rname}",
                    "body": "",
                    "files": [],
                }
            )

            continue
        for commit in ref.commits(num=10, reverse=True):
            cfiles = commit.files()
            if len(cfiles) > 1000:
                cfiles = []  # Crop if payload is too large, prefer dummy payload over nothing.
            send_json({
                "autopublish": via_asfyaml,
                "repository": "git",
                "server": "gitbox",
                "project": cfg.repo_name,
                "ref": commit.ref.name,
                "hash": commit.commit,
                "sha": commit.sha,
                "date": commit.authored,
                "authored": commit.authored,
                "author": commit.author_name,
                "email": commit.author_email,
                "committer": commit.committer,
                "commited": commit.committed,
                "ref_names": commit.ref_names,
                "subject": commit.subject,
                "log": commit.subject,
                "body": commit.body,
                "files": cfiles,
            })


def send_json(data, key = "commit"):
    try:
        # pubsub.a.o payload
        requests.post(
            f"http://pubsub.apache.org:2069/git/{cfg.repo_name}/{key}",
            data=json.dumps({key: data}),
            timeout=10,
        )

    except:
        log.exception()
