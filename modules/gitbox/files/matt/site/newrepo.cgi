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
#

# This is newrepo.cgi - script for self-serve new github/gitbox repos

import hashlib, json, random, os, sys, time, subprocess, re, ldap
import cgi, sqlite3, hashlib, Cookie, urllib, urllib2, ConfigParser
import requests
import smtplib
from email.mime.text import MIMEText
import email.utils

# LDAP settings
CONFIG = ConfigParser.ConfigParser()
CONFIG.read("/x1/gitbox/matt/tools/grouper.cfg")

LDAP_URI = "ldaps://ldap-us-ro.apache.org:636"
LDAP_USER = CONFIG.get('ldap', 'user')
LDAP_PASSWORD = CONFIG.get('ldap', 'password')
UID_RE = re.compile("uid=([^,]+),ou=people,dc=apache,dc=org")
ORG_READ_TOKEN = CONFIG.get('github', 'token')

# Figure out which PMCs/Podlings are allowed
gitdir = '/x1/repos/asf'
allrepos = filter(lambda repo: os.path.isdir(os.path.join(gitdir, repo)), os.listdir(gitdir))

PMCS = {}
# Grab projects from whimsy, sort by tlp/podling status
ap = requests.get('https://whimsy.apache.org/public/public_ldap_projects.json').json()
for project, info in ap['projects'].items():
  if info.get('pmc', False) == True:
    PMCS[project] = 'tlp'
  elif info.get('podling') == 'current':
    PMCS[project] = 'podling'

# CGI
xform = cgi.FieldStorage();

""" Get a POST/GET value """
def getvalue(key):
  return val if (val := xform.getvalue(key)) else None


""" Get LDAP groups a user belongs to """
def ldap_groups(uid):
  ldap.set_option(ldap.OPT_X_TLS_REQUIRE_CERT, ldap.OPT_X_TLS_NEVER)
  l = ldap.initialize(LDAP_URI)
    # this search for all objectClasses that user is in.
    # change this to suit your LDAP schema
  search_filter = f"(|(owner={uid})(owner=uid={uid},ou=people,dc=apache,dc=org))"
  try:
    groups = []
    podlings = {}

    # Is requester in infra-root??
    infra = getStandardGroup('infrastructure-root', 'cn=infrastructure-root,ou=groups,ou=services,dc=apache,dc=org', "member")
    if infra and uid in infra:
        groups.append('infrastructure')
        search_filter= "(|(owner=*)(owner=uid=*,ou=people,dc=apache,dc=org))"

    ipmc = getStandardGroup('incubator')
    isIPMC = bool(ipmc and uid in ipmc)
    LDAP_BASE = "ou=project,ou=groups,dc=apache,dc=org"
    results = l.search_s(LDAP_BASE, ldap.SCOPE_SUBTREE, search_filter, ['cn',])
    for res in results:
      cn = res[1]['cn'][0]
      if (cn in PMCS) or (uid in infra): # Either must be on gitbox or requester from infra-root
        groups.append(cn) # each res is a tuple: ('cn=full,ou=ldap,dc=uri', {'cn': ['tlpname']})
      if cn in PMCS and PMCS[cn] == "podling":
          podlings[cn] = True

    # If in IPMC, add all approved podlings not there yet.
    if isIPMC:
        for cn in PMCS:
            if PMCS[cn] == "podling" and cn not in groups:
                groups.append(cn)
                podlings[cn] =  True

    return [sorted(groups), sorted(podlings), uid in infra]
  except Exception as err:
      pass
  return [[], {}, False]

def getStandardGroup(group, ldap_base = None, what = "owner"):
  """ Gets the list of availids in a standard group (pmcs, services, podlings) """
    # First, check if there's a hardcoded member list for this group
    # If so, read it and return that instead of trying LDAP
  if CONFIG.has_section(f'group:{group}') and CONFIG.has_option(
      f'group:{group}', 'members'):
    return CONFIG.get(f'group:{group}', 'members').split(' ')
  groupmembers = []
    # This might fail in case of ldap bork, if so we'll return nothing.
  try:
    ldapClient = ldap.initialize(LDAP_URI)
    ldapClient.set_option(ldap.OPT_REFERRALS, 0)

    ldapClient.bind(LDAP_USER, LDAP_PASSWORD)

        # Default LDAP base if not specified
    if not ldap_base:
      ldap_base = f"cn={group},ou=project,ou=groups,dc=apache,dc=org"

    # This is using the new podling/etc LDAP groups defined by Sam
    results = ldapClient.search_s(ldap_base, ldap.SCOPE_BASE)

    for result in results:
      result_dn = result[0]
      result_attrs = result[1]
      if what in result_attrs:
        for member in result_attrs[what]:
          if m := UID_RE.match(member):
            groupmembers.append(m.group(1))

    ldapClient.unbind_s()
    groupmembers = sorted(groupmembers) #alphasort
  except Exception as err:
      print(err)
      groupmembers = None
  return groupmembers


def createRepo(repo, title, pmc):
  url = "https://api.github.com/orgs/apache/repos"
  r = requests.post(
      url,
      data=json.dumps({
          'name': repo,
          'description': title,
          'homepage': f"https://{pmc}.apache.org/",
          'private': False,
          'has_issues': False,
          'has_projects': False,
          'has_wiki': False,
      }),
      headers={'Authorization': f"token {ORG_READ_TOKEN}"},
  )

  if r.status_code == 201:
    return True
  print("Status: 200 Okay\r\nContent-Type: application/json\r\n\r\n")
  print(json.dumps({
      'created': False,
      'error': r.text
  }))
  return False

def main():
    action = xform.getvalue("action")
    if action and action == "create":

        # Check if allowed to create
        pmc = xform.getvalue("pmc")
        xuid = os.environ['REMOTE_USER']
        groups, podlings, isRoot = ldap_groups(xuid)

        # Makle sure $uid is (P)PMC member
        if not (pmc in groups) and isRoot == False:
            print("Status: 200 Okay\r\nContent-Type: application/json\r\n\r\n")
            print(json.dumps({
                        'created': False,
                        'error': "You do not have access to create repos for this project!"
                    }))
            return

        # Make sure the project is on gitbox!
        if (pmc in PMCS) or isRoot:

            # Repo name and title
            isPodling = xform.getvalue("ispodling")
            repo = xform.getvalue("name")
            reponame = pmc
            title = "Apache %s" % pmc
            if repo and repo != '-': # - means no repo name, just pmc name. stoopid JS
                reponame = "%s-%s" % (pmc, repo)
                title = "Apache %s %s" % (pmc, repo)
            t = xform.getvalue("description")
            if t:
                title = t
            if isPodling or (pmc in PMCS and PMCS[pmc] == "podling"):
                reponame = "incubator-%s" % reponame
            # Email settings
            commitmail = "commits@%s.apache.org" % pmc
            ghmail = "dev@%s.apache.org" % pmc
            cf = xform.getvalue("notify")
            gf = xform.getvalue("ghnotify")
            if cf:
                commitmail = cf
            if gf:
                ghmail = gf

            # clean up variables
            reponame = re.sub(r"[^-a-zA-Z0-9]+", "", reponame)
            title = re.sub(r"[^-a-zA-Z0-9 .,]+", "", title)
            commitmail = re.sub(r"[^-a-zA-Z0-9@.]+", "", commitmail)
            ghmail = re.sub(r"[^-a-zA-Z0-9@.]+", "", ghmail)

            created = createRepo(reponame, title, pmc)
            if created:
                try:
                    # Clone repo
                    subprocess.check_output("cd /x1/repos/asf/ && /x1/gitbox/bin/gitbox-clone -c %s -d \"%s\" https://github.com/apache/%s.git %s.git" % (commitmail, title, reponame, reponame), shell = True)
                    time.sleep(3) # Wait for GH??
                    # Set apache.dev value in config
                    subprocess.check_output("cd /x1/repos/asf/%s.git/ && git config apache.dev \"%s\"" % (reponame, ghmail), shell = True)

                    # Notify infra@ and private@$pmc that the repo has been set up
                    msg = MIMEText("New repository %s.git was created, as requested by %s.\nYou may view it at: https://gitbox.apache.org/repos/asf/%s.git\n\nWith regards,\nApache Infrastructure." % (reponame, os.environ['REMOTE_USER'], reponame))
                    msg['Subject'] = 'New gitbox/github repository created: %s.git' % reponame
                    msg['From'] = "git@apache.org"
                    msg['Reply-To'] = "users@infra.apache.org"
                    if pmc == 'infrastructure':
                        pmc = 'infra' # hack hack hack
                    msg['To'] = "users@infra.apache.org, private@%s.apache.org" % pmc
                    msg['Date'] = email.utils.formatdate()
                    msg['Message-ID'] = email.utils.make_msgid()

                    s = smtplib.SMTP(host='mail.apache.org', port=2025)
                    s.sendmail("git@apache.org", ["private@infra.apache.org", "private@%s.apache.org" % pmc], msg.as_string())
                    s.quit()


                except subprocess.CalledProcessError as e:
                    print("Status: 500 NOT Okay\r\nContent-Type: application/json\r\n\r\n")
                    print(json.dumps({
                        'created': False,
                        'error': e.output
                    }))


                    # Notify infra@ about this!
                    msg = MIMEText("New repository %s.git creation requested by %s FAILED: \n\n%s" % (reponame, os.environ['REMOTE_USER'], e.output))
                    msg['Subject'] = 'New gitbox/github repository failed: %s.git' % reponame
                    msg['From'] = "git@apache.org"
                    msg['Reply-To'] = "private@infra.apache.org"
                    msg['To'] = "private@infra.apache.org"
                    msg['Date'] = email.utils.formatdate()
                    msg['Message-ID'] = email.utils.make_msgid()

                    s = smtplib.SMTP(host='mail.apache.org', port=2025)
                    s.sendmail("git@apache.org", "private@infra.apache.org", msg.as_string())
                    s.quit()

                    return
            else:
                return
            print("Status: 200 Okay\r\nContent-Type: application/json\r\n\r\n")
            print(json.dumps({
                'created': created
            }))
            return
        else:
            print("Status: 200 Okay\r\nContent-Type: application/json\r\n\r\n")
            print(json.dumps({
                        'created': False,
                        'error': "Project is not GitBox eligible yet!"
                    }))
            return
    if action and action == "pmcs":
        groups, podlings, isroot = ldap_groups(os.environ['REMOTE_USER'])
        print("Status: 200 Okay\r\nContent-Type: application/json\r\n\r\n")
        podling_hash = {}
        for pod in podlings:
            podling_hash[pod] = True
        print(json.dumps({
            'pmcs': groups,
            'podlings': podling_hash,
            'root': isroot
        }))
        return

    print("Status: 200 Okay\r\nContent-Type: application/json\r\n\r\n")
    print(json.dumps({
        'failed': True
    }))


if __name__ == '__main__':
    main()
