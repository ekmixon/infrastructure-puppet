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
This is a retirement script for git repositories on gitbox, git-wip and git.a.o.
When run on git-wip or gitbox, it:
    - Renames the repositories locally
    - Updates git origins
    - Updates mailing list settings
    - Renames the reposiories on GitHub
    - Marks them as archived (read-only)

Usage: attic-repos.py $project, e.g.: attic-repos.py blur
MUST BE RUN AS www-data!
"""
import os
import sys
import re
import requests
import json
import git
import configparser
import pwd

DEBUG = False
REPO_ROOT = "/x1/repos/asf" # Root dir for all repos
CONFIG_FILE = "/x1/gitbox/matt/tools/grouper.cfg" # config file with GH token in it
CONFIG = configparser.ConfigParser()
CONFIG.read(CONFIG_FILE) # Shhhh
TOKEN = CONFIG.get('github', 'token')

def gh_patch(url, payload, token):
    """
    Sends patch requests to github
    """
    headers = {
        'content-type': 'application/json',
    }
    r = requests.patch(url, headers = headers, data = payload, auth = (token, 'x-oauth-basic'))
    if r.status_code == requests.codes.ok:
        return True
    else:
        print("  - Something went wrong :(")
        print(r.text)
        print("Something did not work here, aborting process!!")
        print("Fix the issue and run the tool again.")
        sys.exit(-1)
    
def rename_github_repo(token, old, new):
    """
    Rename an archived repository on GitHub
    """
    # Cut away the .git ending if it's there
    old = old.replace(".git", "")
    new = new.replace(".git", "")

    # API URL for patching the name
    url = "https://api.github.com/repos/apache/%s" % old

    # Rename and Archive repository
    print("  - Changing repository from %s to %s on GitHub and re-setting archive..." % (old, new))
    gh_patch(url, json.dumps({'name': new, 'archived': True}), token)
    print("  - Success!")

def rename_local_repo(old, new, project):
    """
    Renames local repositories:
        - Rename the git dir
        - Change remote origin (svn or git)
        - Change commit notification ML
        - Change PR notification ML
    """
    # First, rename the dir on the box. Fall flat on our behind if this fails.
    print("  - Renaming gitbox repo from %s/%s to %s/%s..." % (REPO_ROOT, old, REPO_ROOT, new))
    os.rename("%s/%s" % (REPO_ROOT, old), "%s/%s" % (REPO_ROOT, new))

    # Change git config options
    gcpath = "%s/%s/config" % (REPO_ROOT, new)
    if not os.path.exists(gcpath):
        gcpath = "%s/%s/.git/config" % (REPO_ROOT, new)
    gconf = git.GitConfigParser(gcpath, read_only = False)

    # Remote origin on GitHub
    if gconf.has_section('remote "origin"'):
        print("  - Setting remote...")
        gconf.set('remote "origin"', 'url', "https://github.com/apache/%s" % new)

    # ML notification targets for commits and PRs
    print("  - Changing notification options..")
    if gconf.has_option('hooks.asfgit', 'recips'):
        ml = 'commits@attic.apache.org'
        print("    - Changing commit ML to %s" % ml)
        gconf.set('hooks.asfgit', 'recips', ml)
    if gconf.has_section('apache') and gconf.has_option('apache', 'dev'):
        ml = 'dev@attic.apache.org'
        print("    - Changing PR notification ML to %s" % ml)
        gconf.set('apache', 'dev', ml)

    # Set GitBox repo to read-only
    if not os.path.isfile("%s/%s/.nocommit" % (REPO_ROOT, new)):
        print("  - Creating %s/%s/.nocommit" % (REPO_ROOT, new))
        open("%s/%s/.nocommit", 'a')
    print("  - Done!")

# Demand being run by www-data or git
me = pwd.getpwuid(os.getuid()).pw_name
if me != "www-data" and me != "git":
    print("You must run this as either www-data (on gitbox/git-wip) or git (on git.a.o)!")
    print("You are running as: %s" % me)
    sys.exit(-1)

# Expect one project name passed on, and only one!
if len(sys.argv) == 2:
    PROJECT = sys.argv[1]
    print("Undoing attic renames for %s..." % PROJECT)
    if os.path.isdir(REPO_ROOT):
        pr = 0
        for repo in os.listdir(REPO_ROOT):
            m = re.match(r"^attic-%s(-.+)?(\.git)?$"% PROJECT, repo)
            if m:
                pr += 1
                new = repo.split('-',1)[-1]
                print("Changing %s to %s..." % (repo, new))
                if not DEBUG:
#                    rename_local_repo(repo, new, PROJECT)
                    rename_github_repo(TOKEN, repo, new)
        print("All done, processed %u repositories!" % pr)
    else:
        print("%s does not seem to be a directory, aborting!" % REPO_ROOT)
else:
    print("Usage: unattic-rename.py $project")
    print("Example: unattic-rename.py blur")
