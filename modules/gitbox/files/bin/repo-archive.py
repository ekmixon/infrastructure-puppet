#!/usr/bin/env python3
# -*- coding: utf-8 -*-
# Licensed to the Apache Software Foundation (ASF) under one or more
# contributor license agreements.  See the NOTICE file distributed with
# this work for additional information regarding copyright ownership.
# The ASF licenses this file to You under the Apache License, Version 2.0
# (the "License"); you may not use this file except in compliance with
# the License.  You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.
"""
This is a retirement script for git repositories on gitbox, and GitHub
When run on gitbox:
    If retire_project is specified:
        - Archives all repositories belonging to a project on GitHub
        - Updates git origins for all newly archived repos
        - Updates mailing list settings if necessary
        - Creates a nocommit file to render the repo read-only
        - Appends '-- Retired' to the repo description.

    If archive_repo is specified:
        - Archived the repository on GitHub
        - Updates the git origin for the corresponding GitBox repo.
        - Creates a nocommit file to render the repo read-only
        - Appends '--Archived' to the repo description.

Usage: repo-archive.py [(-A/--archive_repo)|(-R/--retire_project)] -n/--name,
e.g.:

Retire the entire 'blur' project:
www-data$: python3 ./repo-archive.py -Rn blur

Archive the 'nifi-minifi' repository:
www-data$: python3 ./repo-archive.py -An nifi-minifi

NB: MUST BE RUN AS www-data!
"""

import argparse
import configparser
import datetime
import os
import pwd
import re
import sys
import requests
import yaml

DEBUG = False
REPO_ROOT = "/x1/repos/asf"  # Root dir for all repos
CONFIG_FILE = "/x1/gitbox/matt/tools/grouper.cfg"  # config file with GH token in it
CONFIG = configparser.ConfigParser()
CONFIG.read(CONFIG_FILE)  # Shhhh
TOKEN = CONFIG.get("github", "token")


def update_github_repo(token, repo, debug=False):
    """
    Renames a repository on GitHub by sending a PATCH request.
    """
    # API URL for archiving
    url = f"https://api.github.com/repos/apache/{repo}"

    # Run the request
    if not debug:
        print("  - Changing repository to archived on GitHub...")
        # Headers - json payload + creds
        headers = {
            "content-type": "application/json",
        }
        r = requests.patch(url, headers=headers, json={"archived": True}, auth=(token, "x-oauth-basic"))
        if r.status_code == requests.codes.ok:
            print("  - Repository Archived!")
        else:
            print("  - Something went wrong :(")
            print(r.text)
            print("Something did not work here, aborting process!!")
            print("Fix the issue and run the tool again.")
            sys.exit(-1)
    else:
        print(f"  - Query URL: {url}")
        print("  - Debug set: Skipping...")


def update_local_repo(repo, retire=False, debug=False):
    """
    Renames local repositories:
        - Change PR notification ML if Attic is specified
    - Update the description with '-- Archived'
    - Touch nocommit file to ensure Read Only
    """
    # Change git config options
    if not debug:
        repo = f"{repo}.git"
        if retire:
            # Rewire notifications.yaml to send to @attic.a.o
            noti_file = os.path.join(REPO_ROOT, repo, "notifications.yaml")
            retire_config = {
                "commits": "commits@attic.apache.org",
                "pullrequests": "dev@attic.apache.org",
                "issues": "dev@attic.apache.org",
            }
            yaml.dump(retire_config, open(noti_file, "w"))
            description = " -- Retired"
        else:
            description = " -- Archived"

        # Update Repo description
        desc_file = os.path.join(REPO_ROOT, repo, "description")
        if os.path.isfile(desc_file):
            print(f"  - Updating description file {desc_file}")
            with open(desc_file, "a+") as desc:
                desc.write(description)
                desc.close()

        # Set GitBox repo to read-only
        print("  - Setting Archive on GitBox")
        nocommit_file = os.path.join(REPO_ROOT, repo, "nocommit")
        if not os.path.isfile(nocommit_file):
            print(f"  - Creating {nocommit_file}")
            with open(nocommit_file, "w+") as f:
                f.write(f"Repository retired at {datetime.datetime.now().isoformat()}")
        print("  - Success!")
        print("  - Done!")

    else:
        print("  - Debug set, Skipping...")


def main():
    # Demand being run by www-data or git
    me = pwd.getpwuid(os.getuid()).pw_name
    if me not in ("www-data", "git",):
        print("You must run this as either www-data (on gitbox/git-wip) or git (on git.a.o)!")
        print(f"You are running as: {me}")
        sys.exit(-1)

    parser = argparse.ArgumentParser(description="Apache Git repository archival utility")
    actions = parser.add_mutually_exclusive_group(required=True)
    actions.add_argument(
        "-R", "--retire-project", action="store_true", help="Archive *ALL* repos belonging to project",
    )
    actions.add_argument(
        "-A", "--archive-repo", action="store_true", help="Archive single repository by name",
    )
    parser.add_argument("-n", "--name", help="Archive target name")
    parser.add_argument("-d", "--debug", action="store_true", help="debug switch")
    args = parser.parse_args()

    # Expect one project name passed on, and only one!
    if not os.path.isdir(REPO_ROOT):
        print(f"{REPO_ROOT} does not seem to be a directory, aborting!")
        sys.exit(-1)

    if args.retire_project:
        print("Attic'ing %s..." % args.name)
        if os.path.isdir(REPO_ROOT):
            pr = 0
            for repo in os.listdir(REPO_ROOT):
                if m := re.match(r"^%s(-.+)?(\.git)?$" % args.name, repo):
                    pr += 1
                    print(f"Archiving {repo}...")
                    update_local_repo(repo, retire=True, debug=args.debug)
                    update_github_repo(TOKEN, repo, debug=args.debug)
            print("All done, processed %u repositories!" % pr)

    if args.archive_repo:
        repo = args.name
        if os.path.isdir(os.path.join(REPO_ROOT, f"{args.name}.git")):
            print(f"Archiving {args.name}...")
            update_local_repo(repo, debug=args.debug)
            update_github_repo(TOKEN, repo, debug=args.debug)
        print("All done!")


if __name__ == "__main__":
    main()
