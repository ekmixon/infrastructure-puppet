#!/usr/bin/env python
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
This is a migration script for git repositories on gitbox, git-wip and git.a.o.
When run on git-wip or gitbox, it:
    - Renames the repositories locally
    - Updates git origins
    - Updates mailing list settings
    - Renames the reposiories on GitHub

When run on git.a.o, it:
    - Renames the repository
    - Updates SVN remote if this is a SVN mirror

Usage: graduate-podling.py $project, e.g.: graduate-podling.py ponymail
MUST BE RUN AS www-data OR git USER!
"""
import os
import sys
import re
import requests
import json
import git
import ConfigParser
import pwd

REPO_ROOT = "/x1/repos/asf" # Root dir for all repos
CONFIG_FILE = "/x1/gitbox/matt/tools/grouper.cfg" # config file with GH token in it
IS_MIRROR = False # Set to True on git.a.o to avoid a GitHub call!

CONFIG = ConfigParser.ConfigParser()
TOKEN = None
if not IS_MIRROR:
    CONFIG.read(CONFIG_FILE) # Shhhh
    TOKEN = CONFIG.get('github', 'token')

def rename_github_repo(token, old, new):
    """
    Renames a repository on GitHub by sending a PATCH request.
    """
    # Cut away the .git ending if it's there
    old = old.replace(".git", "")
    new = new.replace(".git", "")

    # API URL for patching the name
    url = f"https://api.github.com/repos/apache/{old}"

    # Headers - json payload + creds
    headers = {
        'content-type': 'application/json',
    }

    # Construct payload
    payload = json.dumps({
        'name': new
    })

    # Run the request
    print(f"  - Changing repository from {old} to {new} on GitHub...")
    r = requests.patch(url, headers = headers, data = payload, auth = (token, 'x-oauth-basic'))
    if r.status_code == requests.codes.ok:
        print("  - Repository name changed!")
    else:
        print("  - Something went wrong :(")
        print(r.text)
        print("Something did not work here, aborting process!!")
        print("Fix the issue and run the tool again.")
        sys.exit(-1)

def rename_local_repo(old, new, project):
    """
    Renames local repositories:
        - Rename the git dir
        - Change remote origin (svn or git)
        - Change commit notification ML
        - Change PR notification ML
    """
    # First, rename the dir on the box. Fall flat on our behind if this fails.
    print(
        f"  - Renaming gitbox repo from {REPO_ROOT}/{old} to {REPO_ROOT}/{new}..."
    )

    os.rename(f"{REPO_ROOT}/{old}", f"{REPO_ROOT}/{new}")

    # Change git config options
    gcpath = f"{REPO_ROOT}/{new}/config"
    if not os.path.exists(gcpath):
        gcpath = f"{REPO_ROOT}/{new}/.git/config"
    gconf = git.GitConfigParser(gcpath, read_only = False)

    # Remote origin on GitHub
    if gconf.has_section('remote "origin"'):
        print("  - Setting remote...")
        gconf.set('remote "origin"', 'url', f"https://github.com/apache/{new}")

    # Remote copy on GitHub
    if gconf.has_section('remote "github-copy"'):
        print("  - Setting remote...")
        gconf.set('remote "github-copy"', 'url', f"https://github.com/apache/{new}")

    # Remote SVN origin?
    if gconf.has_section('svn-remote "svn"'):
        svnremote = gconf.get('svn-remote "svn"', 'url')
        newsvn = svnremote.replace("/incubator/", "/")
        print("  - Setting SVN remote from %s to %s...")
        gconf.set('svn-remote "svn"', 'url', newsvn)

    # ML notification targets for commits and PRs
    print("  - Changing notification options..")
    if gconf.has_option('hooks.asfgit', 'recips'):
        ml = gconf.get('hooks.asfgit', 'recips')
        ml = re.sub(r"incubator\.", "", ml)
        print(f"    - Changing commit ML to {ml}")
        gconf.set('hooks.asfgit', 'recips', ml)
    if gconf.has_section('apache') and gconf.has_option('apache', 'dev'):
        ml = gconf.get('apache', 'dev')
        ml = re.sub(r"incubator\.", "", ml)
        print(f"    - Changing PR notification ML to {ml}")
        gconf.set('apache', 'dev', ml)

    print("  - Done!")

# Demand being run by www-data or git
me = pwd.getpwuid(os.getuid()).pw_name
if me not in ["www-data", "git"]:
    print("You must run this as either www-data (on gitbox/git-wip) or git (on git.a.o)!")
    print(f"You are running as: {me}")
    sys.exit(-1)

# Expect one project name passed on, and only one!
if len(sys.argv) == 2:
    PROJECT = sys.argv[1]
    print(f"Graduating {PROJECT}...")
    if os.path.isdir(REPO_ROOT):
        pr = 0
        for repo in os.listdir(REPO_ROOT):
            if m := re.match(r"incubator-%s(-.+)?(\.git)?$" % PROJECT, repo):
                pr += 1
                print(f"- Applying changes to {repo} ...")
                new = repo.replace("incubator-", "")
                rename_local_repo(repo, new, PROJECT)
                if not IS_MIRROR:
                    rename_github_repo(TOKEN, repo, new)
        print("All done, processed %u repositories!" % pr)
    else:
        print(f"{REPO_ROOT} does not seem to be a directory, aborting!")
else:
    print("Usage: graduate-podling.py $podling")
    print("Example: graduate-podling.py openwhisk")
