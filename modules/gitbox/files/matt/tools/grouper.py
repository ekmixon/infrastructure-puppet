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

import ConfigParser
import json
import logging
import os
import re
import sqlite3
import sys
import time
import ldap
import requests

logging.basicConfig(filename='grouper.log',
                    format='[%(asctime)s]: %(message)s', level=logging.INFO)

# Git base dirs
GIT_DIRS = ('/x1/repos/asf', '/x1/repos/private')

# LDAP Defs
UID_RE = re.compile("uid=([^,]+),ou=people,dc=apache,dc=org")

# Run `python grouper.py debug` to check teams but not add/remove users
DEBUG_RUN = len(sys.argv) > 1 and sys.argv[1] == 'debug'
if DEBUG_RUN:
    print("Debug run active! Not modifying teams")
CONFIG = ConfigParser.ConfigParser()
CONFIG.read("grouper.cfg")  # Yeah, you're not getting this info...

LDAP_URI = "ldaps://ldap-us-ro.apache.org:636"
LDAP_USER = CONFIG.get('ldap', 'user')
LDAP_PASSWORD = CONFIG.get('ldap', 'password')

MATT_PROJECTS = {}
ORG_READ_TOKEN = CONFIG.get('github', 'token')

logging.info("Preloading 2FA JSON index...")
MFA = json.load(open("../mfa.json"))

# GH Mappings
WRITERS = {}
LINKS = {}

def getJSON(url):
    cont = True
    tries = 0
    while cont:
        tries = tries + 1
        if tries > 5:
            logging.warning(f"Giving up on URL {url}")
            return []
        try:
            rv = requests.get(url, auth = ('asf-gitbox', ORG_READ_TOKEN))
            if rv.status_code != 200:
                rv.raise_for_status()
            return rv.json()
        except requests.HTTPError as e:
            sc = e.response.status_code
            logging.warning(
                f"GitHub responsed with error code {sc} on URL {url.replace(ORG_READ_TOKEN, 'XXXX')}"
            )

            if 'abuse' in e.response.text:
                logging.warn("Hit GitHub's abuse detector, sleeping it off")
                time.sleep(10)
            elif 'API rate limit exceeded' in e.response.text:
                logging.error("API Rate limit hit, cannot continue!")
                sys.stderr.write(e.response.text)
                sys.exit(-1)
            else:
                logging.error(f"Unknown error code {sc}, aborting: {e.response.text}")
                sys.stderr.write(e.response.text)
                sys.exit(-1)

def getGitHubTeams():
    """Fetches a list of all GitHub committer teams (projects only, not the
    parent org team or the admin teams)"""
    logging.info("Fetching GitHub teams...")
    teams = {}
    for n in range(1, 100):
        url = "https://api.github.com/orgs/apache/teams?page=%u" % n
        data = getJSON(url)
        # Break if we've hit the end
        if len(data) == 0:
            break

        for entry in data:
            if m := re.match(r"^(.+)-committers$", entry['slug']):
                project = m[1]
                # We don't want the umbrella team
                if project != 'apache':
                    teams[entry['id']] = project
                    logging.info(f"found team: {project}-committers")
    return teams


def getGitHubRepos():
    """ Fetches all GitHub repos we own """
    logging.info(
        "Fetching list of GitHub repos, hang on (this may take a while!)..")
    repos = []
    for n in range(1, 150):  # 150 would be 4500 repos, we have 1750ish now...
        url = "https://api.github.com/orgs/apache/repos?page=%u" % n
        data = getJSON(url)
        # Break if no more repos
        if len(data) == 0:
            break
        repos.extend(repo['name'] for repo in data)
    return sorted(repos)


def getGitHubTeamMembers(teamID):
    """Given a Team ID, fetch the current list of members of the team"""
    members = []
    if str(int(teamID)) != str(teamID):
        logging.warning("Bad Team ID passed!!")
        return None
    for n in range(1, 100):  # 100 would be 3000 members
        url = "https://api.github.com/teams/%s/members?page=%u" % (
            teamID, n)
        data = getJSON(url)
        # Break if no more members
        if len(data) == 0:
            break
        members.extend(member['login'] for member in data)
    return sorted(members)


def getGitHubTeamRepos(teamID):
    """Given a Team ID, fetch the current list of repos in the team"""
    repos = []
    if str(int(teamID)) != str(teamID):
        logging.warning("Bad Team ID passed!!")
        return None
    for n in range(1, 50): # 50 pages = 1000 repos max
        url = "https://api.github.com/teams/%s/repos?per_page=20&page=%u" % (
            teamID, n)
        data = getJSON(url)
        # Break if no more members
        if len(data) == 0:
            break
        repos.extend(repo['name'] for repo in data)
    return sorted(repos)


def createGitHubTeam(project):
    """ Given a project, try to create it as a GitHub team"""
    logging.info(f"- Trying to create {project} as a GitHub team...")
    # Make sure we only allow the ones with permission to use MATT
    if project not in MATT_PROJECTS:
        logging.error(
            " - This project has not been cleared for GitBox yet. Aborting team creation")
        return False

    url = "https://api.github.com/orgs/apache/teams"
    data = json.dumps({'name': f"{project} committers"})
    r = requests.post(url, data=data, allow_redirects=True, auth = ('asf-gitbox', ORG_READ_TOKEN))
    data = json.loads(r.content)
    if data and 'id' in data:
        logging.info(f"New GitHub team created as #{str(data['id'])}")
        return data['id']
    else:
        logging.warning(
            "Unknown return code, dunno if the team was created or not...?")
        logging.warning(data)
        return None


def removeGitHubTeamMember(teamID, login):
    """ Remove a team member from a team """
    if str(int(teamID)) != str(teamID):
        logging.warning("Bad Team ID passed!!")
        return None
    if login.lower() == 'humbedooh' or login.startswith('asf-ci'):
        logging.info("Not removing this account (infra)")
        return
    logging.info(f"- Removing {login} from team #{str(teamID)}...")
    url = f"https://api.github.com/teams/{teamID}/memberships/{login}"
    r = requests.delete(url, headers={'Authorization': f"token {ORG_READ_TOKEN}"})

    if r.status_code <= 204:
        logging.info("- Removal done!")
    else:
        logging.error("- Error occurred while trying to remove member!")
        logging.error(r.status_code)


def addGitHubTeamMember(teamID, login):
    """ Add a member to a team """
    if str(int(teamID)) != str(teamID):
        logging.warning("Bad Team ID passed!!")
        return None
    logging.info(f"- Adding {login} to team #{str(teamID)}...")
    url = f"https://api.github.com/teams/{teamID}/memberships/{login}"
    r = requests.put(url, headers={'Authorization': f"token {ORG_READ_TOKEN}"})
    data = json.loads(r.content)
    if 'state' in data:
        logging.info("- Additions done!")
    else:
        logging.error("- Error occurred while trying to add member!")
        logging.error(data)


def addGitHubTeamRepo(teamID, repo):
    """ Add a repo to a team """
    if str(int(teamID)) != str(teamID):
        logging.warning("Bad Team ID passed!!")
        return None
    logging.info(f"- Adding repo {repo} to team #{str(teamID)}...")
    url = f"https://api.github.com/teams/{teamID}/repos/apache/{repo}"
    r = requests.put(
        url,
        data="{\"permission\": \"push\"}",
        headers={'Authorization': f"token {ORG_READ_TOKEN}"},
    )

    if r.status_code <= 204:
        logging.info("- Team successfully subscribed to repo!")
    else:
        logging.error("- Error occurred while trying to add repo!")
        logging.error(r.content)


def getStandardGroup(group):
    """ Gets the list of availids in a standard group (pmcs, services, podlings) """
    logging.info(f"Fetching LDAP group list for {group}")
    ldap_base = f"cn={group},ou=project,ou=groups,dc=apache,dc=org"
    # First, check if there's a hardcoded member list for this group
    # If so, read it and return that instead of trying LDAP
    if CONFIG.has_section(f'group:{group}') and CONFIG.has_option(
        f'group:{group}', 'members'
    ):
        logging.warning(f"Found hardcoded member list for {group}!")
        return CONFIG.get(f'group:{group}', 'members').split(' ')
    if CONFIG.has_section(f'group:{group}') and CONFIG.has_option(
        f'group:{group}', 'ldap'
    ):
        ldap_base = CONFIG.get(f'group:{group}', 'ldap')
    ldap_key = "member"
    if CONFIG.has_section(f'group:{group}') and CONFIG.has_option(
        f'group:{group}', 'ldapkey'
    ):
        ldap_key = CONFIG.get(f'group:{group}', 'ldapkey')
    groupmembers = []
    # This might fail in case of ldap bork, if so we'll return nothing.
    try:
        ldapClient = ldap.initialize(LDAP_URI)
        ldapClient.set_option(ldap.OPT_REFERRALS, 0)

        ldapClient.bind(LDAP_USER, LDAP_PASSWORD)

        # This is using the new podling/etc LDAP groups defined by Sam
        results = ldapClient.search_s(ldap_base, ldap.SCOPE_BASE)

        for result in results:
            result_dn = result[0]
            result_attrs = result[1]
            # We are only interested in the member attribs here. owner == ppmc,
            # but we don't care
            if ldap_key in result_attrs:
                for member in result_attrs[ldap_key]:
                    if m := UID_RE.match(member):
                        groupmembers.append(m.group(1))

        ldapClient.unbind_s()
        groupmembers = sorted(groupmembers)  # alphasort
    except Exception as err:
        logging.error(f"Could not fetch LDAP data: {err}")
        groupmembers = None
    return groupmembers


####################
# MAIN STARTS HERE #
####################


# Get a list of all asf/github IDs
logging.info("Loading all ASF<->GitHub links from gitbox.db")
conn = sqlite3.connect('/x1/gitbox/db/gitbox.db')
cursor = conn.cursor()

cursor.execute("SELECT asfid,githubid,mfa FROM ids")
accounts = cursor.fetchall()

conn.close()
logging.info("Found %u account links!" % len(accounts))

# get a list of all repos that are active on gitbox
allrepos = []
for gitdir in GIT_DIRS:
  allrepos.extend(repo for repo in os.listdir(gitdir) if os.path.isdir(os.path.join(gitdir, repo)))

# turn that into a list of projects to run the manager for
for repo in allrepos:
    if m := re.match(r"(?:incubator-)?(empire-db|[^-.]+)(?:.*\.git)", repo):
        project = m[1]
        if project not in MATT_PROJECTS and project not in ['apache']: # disallow 'apache' et al as group name.
            MATT_PROJECTS[project] = (
                "podling" if re.match(r"incubator-", repo) else "tlp"
            )


# Then, start off by getting all existing GitHub teams and repos - we'll
# need that later.
existingTeams = getGitHubTeams()
existingRepos = getGitHubRepos()


# Process each project in the MATT test
for project in sorted(MATT_PROJECTS):
    logging.info(f"Processing GitHub team for {project}")
    ptype = MATT_PROJECTS[project]

    # Does the team exist?
    teamID = None
    for team in existingTeams:
        if existingTeams[team] == project:
            teamID = team
            logging.info("- Team exists on GitHub")
            break
    # If not found, create it (or try to, stuff may break)
    if not teamID:
        logging.info("- Team does not yet exist on GitHub, creating...")
        teamID = createGitHubTeam(project)
    if not teamID:
        logging.error("Something went very wrong here, aborting!")
        break

    # Make sure all $tlp-* repos are writeable by this team
    teamRepos = getGitHubTeamRepos(teamID)
    logging.info("Team is subbed to the following repos: " +
                 ", ".join(teamRepos))
    for repo in existingRepos:
        m = re.match(r"^(?:incubator-)?(empire-db|[^-]+)-?", repo)
        p = m[1]
        if (
            p == project
            and repo not in teamRepos
            and os.path.exists(f"/x1/repos/asf/{repo}.git")
        ):
            logging.info(f"Need to add {repo} repo to the team...")
            addGitHubTeamRepo(teamID, repo)

    # Now get the current list of members on GitHub
    members = getGitHubTeamMembers(teamID)
    if teamID in existingTeams:
        logging.info(f"{existingTeams[teamID]}: " + ", ".join(members))

    # Now get the committer availids from LDAP
    ldap_team = getStandardGroup(project)
    if not ldap_team or len(ldap_team) == 0:
        logging.warning(
            "LDAP Borked (no group data returned)? Trying next project instead")
        continue

    # For each committer, IF THEY HAVE MFA, add them to a 'this is what it
    # should look like' list
    hopefulTeam = []
    for committer in ldap_team:
        githubID = None
        for account in accounts:
            # Check that we found a match
            if account[0].lower() == committer:
                githubID = account[1]
        # Make sure we found the user and the latest MFA scan shows MFA enabled
        if githubID and githubID in MFA['enabled']:
            hopefulTeam.append(githubID)
        elif githubID and githubID in MFA['disabled']:
            logging.warning(
                githubID + " does not have MFA enabled, can't add to team")
        elif githubID:
            logging.error(
                f"{githubID} does not seem to be in the MFA JSON (neither disabled nor enabled); likely: unaccepted org invite"
            )

        else:
            logging.warning(
                f"{committer} does not seem to have linked ASF and GitHub ID at gitbox.a.o/setup yet (not found in gitbox.db), ignoring"
            )


    # If no team, assume something broke for now
    if not hopefulTeam:
        logging.warning(
            "No hopeful GitHub team could be constructed, assuming something's wrong and cycling to next project")
        continue

    # Now, for each member in the team, find those that don't belong here.
    for member in members:
        if member not in hopefulTeam:
            logging.info(f"{member} should not be a part of this team, removing...")
            if not DEBUG_RUN:
                removeGitHubTeamMember(teamID, member)

    # Lastly, add those that should be here but aren't
    for member in hopefulTeam:
        if member not in members:
            logging.info(f"{member} not found in GitHub team, adding...")
            if not DEBUG_RUN:
                addGitHubTeamMember(teamID, member)

    # Add writers to GH map
    WRITERS[project] = hopefulTeam

    logging.info(f"Done with {project}, moving to next project...")

# Spit out JSON github map
for account in accounts:
    LINKS[account[0].lower()] = account[1]
with open("/x1/gitbox/matt/site/ghmap.json", "w") as f:
    json.dump({
        'repos': WRITERS,
        'map': LINKS
    }, f)
    f.close()

logging.info("ALL DONE WITH THIS RUN!")
