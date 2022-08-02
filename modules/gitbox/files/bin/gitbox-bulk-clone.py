#!/usr/bin/env python
#
# Licensed to the Apache Software Foundation (ASF) under one or more
# contributor license agreements.  See the NOTICE file distributed with
# this work for additional information regarding copyright ownership.
# The ASF licenses this file to You under the Apache License, Version 2.0
# (the "License"); you may not use this file except in compliance with
# the License.  You may obtain a copy of the License at
#
# http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

# This is gitbox-bulk-clone.py: bulk cloning for entire projects.
# Usage: gitbox-bulk-clone.py $project [optinal mailing list] [dryrun]
# If mailing list is omitted, commits@$project.apache.org is the default.
# Use the dryrun arg as the last arg to make it just run through the
# repos that would be cloned but not actually clone them.

import os
import sys
import urllib2
import requests
import json
import ConfigParser
import subprocess

CONFIG_FILE = "/x1/gitbox/matt/tools/grouper.cfg" # config file with GH token in it

CONFIG = ConfigParser.ConfigParser()
CONFIG.read(CONFIG_FILE)
ORG_TOKEN = CONFIG.get('github', 'token')

def getGitHubRepos():
    """ Fetches all GitHub repos we own """
    print("Fetching list of GitHub repos, hang on (this may take a while!)..")
    repos = {} # key/value with reponame: description
    for n in range(1, 100): # 100 would be 3000 repos, we have 750ish now...
        url = "https://api.github.com/orgs/apache/repos?access_token=%s&page=%u" % (ORG_TOKEN, n)
        response = urllib2.urlopen(url)
        data = json.load(response)
        # Break if no more repos
        if len(data) == 0:
            break
        for repo in data:
            rname = repo['name']
            if not repo['description']:
                print(f"Warning: {rname} has no description set! ")
                repos[rname] = f"Apache {rname.split('-')[0]}"
            else:
                repos[rname] = repo['description'].replace("Mirror of ", "")
    return repos

def rmWebhooks(repo):
    """Checks for and removes stale web hooks"""
    url = f"https://api.github.com/repos/apache/{repo}/hooks?access_token={ORG_TOKEN}"

    response = urllib2.urlopen(url)
    data = json.load(response)
    for hook in data:
        # Is this an old git-wip hook?
        if (
            'config' in hook
            and hook['config'].get('url')
            and (
                'git-wip' in hook['config']['url']
                or 'git1-us-east' in hook['config']['url']
            )
        ):
            print(f"Removing stale webhook {hook['url']} ({hook['config']['url']})")
            requests.delete(f"{hook['url']}?access_token={ORG_TOKEN}")
            

if len(sys.argv) < 2:
    print("Usage: gitbox-bulk-clone.py $project [$commitlist] [dryrun]")
    print("Examples: ")
    print("gitbox-bulk-clone couchdb")
    print("gitbox-bulk-clone httpd cvs@httpd.apache.org")
    sys.exit(-1)

project = sys.argv[1]
commitlist = f"commits@{project}.apache.org"

if len(sys.argv) > 2 and sys.argv[2] != 'dryrun':
    commitlist = sys.argv[2]

if 'dryrun' in sys.argv:
    print("DRY RUN! No actual changes will be made, nothing will be cloned.")

repos = getGitHubRepos()
r = 0
for repo in repos:
    # Get foo-bar.git and foo.git for project foo
    if repo.startswith(f"{project}-") or repo == project:
        # Set defaults: github URL, repo description and local file path
        repourl = f"https://github.com/apache/{repo}.git"
        description = repos[repo]
        location = f"/x1/repos/asf/{repo}.git"
        # Skip if the repo is already on gitbox
        if os.path.exists(location):
            print(f"Skipping {repo}.git as it already exists on gitbox!")
        else:
            print(f"Cloning {repourl} ({description}) to gitbox...")
            if 'dryrun' not in sys.argv:
                try:
                    subprocess.check_output(['/usr/local/bin/python', '/x1/gitbox/bin/gitbox-clone', '-d', description, '-c', commitlist, repourl, location])
                    print("Done cloning, chowning...")
                    subprocess.check_output(['/bin/chown', '-R', 'www-data', location])
                    print(f"Successfully cloned {location}")
                    rmWebhooks(repo)
                except subprocess.CalledProcessError as err:
                    print("FAILED! Output was:")
                    print(err.output)
                    yn = input("Should we continue with other repos? (y/n): ")
                    if yn.lower() == "n":
                        print("Aborting bulk clone!")
                        sys.exit(-1)
            else:
                print("Dry run, not exetucing for reals...")
            r += 1

print("All done! Processed %u repos." % r)
