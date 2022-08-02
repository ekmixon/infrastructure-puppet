#!/usr/bin/env python

import os
import sys
import re
import git

WSMAP = {
    'whimsy': 'whimsical',
    'empire': 'empire-db',
    'webservices': 'ws',
    'infrastructure': 'infra',
    'comdev': 'community',
}


def main():
    reponame = os.environ.get('QUERY_STRING', '')
    if not reponame or not re.match(r"^[-_a-z0-9]+(\.git)?$", reponame):
        print("Status: 404 Not Found")
        print("Content-Type: text/plain")
        print("")
        print("No such repository!")
    else:
        if not reponame.endswith('.git'):
            reponame += '.git'
        if not os.path.exists(f'/x1/repos/asf/{reponame}'):
            print("Status: 404 Not Found")
            print("Content-Type: text/plain")
            print("")
            print("Repository not found")
        else:
            m = re.match(r"(?:incubator-)?([^-.]+)", reponame)
            pname = m[1]
            pname = WSMAP.get(pname, pname)
            config = git.GitConfigParser(f'/x1/repos/asf/{reponame}/config')
            commitmail = config.get('hooks.asfgit', 'recips')
            devmail = f'dev@{pname}.apache.org'
            if config.has_option('apache', 'dev'):
                devmail = config.get('apache', 'dev')
            jira = 'link label'
            if config.has_option('apache', 'jira'):
                jira = config.get('apache', 'jira')
            print("Status: 200 Okay")
            print("Content-Type: text/html")
            print("")
            print("""
<h2>.asf.yaml notification settings for %s:</h2>
The below YAML snippet depicts your current default settings for %s:<br/>
<pre style="border: 1px dotted #3333; background: #FFD; border-radius: 4px; padding: 4px;">
<b>notifications:</b>
    <b>commits:</b>      %s
    <b>issues:</b>       %s
    <b>pullrequests:</b> %s
    <b>jira_options:</b> %s
    </pre>
To change them, please commit your changes to your <a href='https://s.apache.org/asfyaml'>.asf.yaml</a> file in your repository.<br/>
Note that all changes will cause the (P)PMC to be notified, and must be made in the master/trunk branch.
            """ % (reponame, reponame, commitmail, devmail, devmail, jira))

if __name__ == '__main__':
    main()
