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

This script determines the intended ASF recipient of an email and
archives the email in the correct mbox file. Does not use the
list name to differentiate between public and private email. That
distinction is controlled by the optional security realm argument.


Arguments (optional):
    --lid abcd@xyz.apache.org - use this instead of parsing list-post

    <security-realm> (optional)
    - restricted - file the mail under the directory defined by the 'restricteddir' config item
    - private    - file the mail under the directory defined by the 'privatedir' config item
    - anything else, file it under the directory defined by the 'archivedir' config item

   The above can be combined if required.

Usage:

The script is normally installed as a mail alias file.
Examples:

archiver:
|python3 ${install_base}/tools/archive.py

private:
|python3 ${install_base}/tools/archive.py private

president:
|python3 ${install_base}/tools/archive.py --lid president@apache.org private

"""


import email.parser
import time
import re
import yaml
import os
import io
import sys
import stat
import fcntl
import errno
import argparse
import msgbody
import requests

# Fetch config yaml
cpath = os.path.dirname(os.path.realpath(__file__))
try:
    config = yaml.safe_load(open(f"{cpath}/settings.yml"))
except:
    print("Can't find config, using defaults (/x1/archives/)")
    config = {
        'archivedir': '/x1/archives',
        'privatedir': '/x1/private',
        'restricteddir': '/x1/restricted',
        'dumpfile': '/x1/archives/bademails.txt'
    }

# validate an email argument
def valid_mail(m):
    if re.match(r"^.+?@(.*apache\.org|apachecon\.com)$", m):
        return m
    else:
        raise argparse.ArgumentTypeError("%r is not a valid ASF email address" % m)

parser = argparse.ArgumentParser()
parser.add_argument("--lid", type=valid_mail, help="override list id")
parser.add_argument("security", nargs='?') # e.g. restricted, private or omitted
args = parser.parse_args()

def lock(fd):
    """ Attempt to lock a file, wait 0.1 secs if failed. """
    while True:
        try:
            fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
            break
        except BlockingIOError as e:
            if e.errno in [errno.EAGAIN, errno.EACCES]:
                time.sleep(0.1)
            else:
                raise

def dumpbad(what):
    with open(config['dumpfile'], "ab") as f:
        lock(f) # Lock the file
        # The From ... line will always be there, or we couldn't have
        # received the msg in the first place.
        # Write the body, escape lines starting with "(>*)From ..." as ">(>*)From ..."
        # First line must not get an extra LF prefix
        f.write(re.sub(b"\n(>*)From ", b"\n>\\1From ", what))
        # End with one blank line
        f.write(b"\n")
        f.close() # implicitly releases the lock


def redact(sender):
    if m := re.match(r"(.+)\s*<.+>", sender):
        return m[1].strip()
    if m := re.match(r"<?(.)(.*)@(.+)>?", sender):
        return f"{m[1]}...@{m[3]}"
    return '?@?'


def main():
    input_stream = sys.stdin.buffer

    msgstring = input_stream.read()
    msg = None

    # Try parsing the email headers
    try:
        msg = email.parser.BytesHeaderParser().parsebytes(msgstring)
    except Exception as err:
        print(f"STDIN parser exception: {err}")

    # If email wasn't valid, dump it in the bademails file
    if msgstring and not msg:
        print(f"Invalid email received, dumping in {config['dumpfile']}!")
        dumpbad(msgstring)
        sys.exit(0) # Bail quietly

    # So, we got an email now - who is it for??

    # Have we got a list id override?
    recipient = args.lid

    # If not, try List-Post
    if not recipient:
        if header := msg.get('list-post'):
            print(header)
            if m := re.match(r"<mailto:(.+?@.*?)>", header):
                recipient = m[1]
            else:
                print(f"Unexpected list-post: {header}")
        else:
            print(f"Missing list-post: {msg.get_unixfrom()}")

    if recipient:
        # validate listname and fqdn, just in case
        listname, fqdn = recipient.lower().split('@', 1)
        # Underscore needed for mod_ftp
        if not re.match(r"^[a-z0-9][-_.a-z0-9]*$", listname) or not re.match(r"^[a-z0-9][-.a-z0-9]*$", fqdn):
            # N.B. the parts are used as path name components so need to be safe for use
            print("Dirty listname or FQDN in '%s', dumping in %s!" % (recipient, config['dumpfile']))
            dumpbad(msgstring)
            sys.exit(0) # Bail quietly
        fqdn = fqdn.replace('.incubator.', '.') # INFRA-18153 - remove .incubator path segment
        YM = time.strftime("%Y%m", time.gmtime()) # Use UTC
        adir = config['archivedir']
        dochmod = True
        if args.security == 'private':
            adir = config['privatedir']
        elif args.security == 'restricted':
            adir = config['restricteddir']
            dochmod = False
        # Construct a path to the mbox file
        fqdnpath = os.path.join(adir, fqdn)
        listpath = os.path.join(fqdnpath, listname)
        path = os.path.join(listpath, f"{YM}.mbox")
        print(f"This is for {recipient}, archiving under {path}!")
        # Show some context in case the IO fails:
        print(f"Return-Path: {msg.get('Return-Path')}")
        print(f"Message-Id: {msg.get('Message-Id')}")
        if not os.path.exists(listpath):
            print(f"Creating directory {listpath} first")
            os.makedirs(listpath, exist_ok = True)
            # Since we're running as nobody, we need to...massage things for now
            # chmod fqdn and fqdn/list as 0705
            if dochmod:
                os.chmod(fqdnpath, stat.S_IWUSR | stat.S_IRUSR | stat.S_IXUSR | stat.S_IROTH | stat.S_IXOTH)
                os.chmod(listpath, stat.S_IWUSR | stat.S_IRUSR | stat.S_IXUSR | stat.S_IROTH | stat.S_IXOTH)
        with open(path, "ab") as f:
            lock(f) # Lock the file
            # Write the body, escape lines starting with "(>*)From ..." as ">(>*)From ..."
            # First line is the From_ line so must not be escaped
            # Actual message Header lines cannot start with '>*From '
            f.write(re.sub(b"\n(>*)From ", b"\n>\\1From ", msgstring))
            # End with one blank line
            f.write(b"\n")
            f.close() # Implicitly releases the lock
            os.chmod(path, stat.S_IWUSR | stat.S_IRUSR | stat.S_IROTH)

        # If public email on standard open channels, we can notify pypubsub
        if not args.security and listname in ['user', 'users', 'dev', 'issues']:
            payload = {
                'email': {
                    'domain': fqdn,
                    'list': listname,
                    'list_full': f'{listname}@{fqdn}',
                    'sender': redact(msg.get('From', '?@?')),
                    'subject': msg.get('Subject'),
                    'message-id': msg.get('Message-ID', ''),
                    'snippet': msgbody.get_body(msg)[:200],
                }
            }

            try:
                rv = requests.post(
                    f'http://pubsub.apache.org:2069/email/{fqdn}/{listname}',
                    json=payload,
                )

            except:
                pass
    else:
        # If we can't find a list for this, still valuable to print out what happened.
        # We shouldn't be getting emails we can't find a valid list for!
        sys.stderr.write("Valid email received, but appears it's not for us!\n")
        sys.stderr.write("  List-Post: %s\n  From: %s\n  To: %s\n  Message-ID: %s\n\n" % \
            (msg.get('list-post', "Unknown"), msg.get('from', "Unknown"), msg.get('to', "Unknown"), msg.get('message-id', "Unknown")))
        dumpbad(msgstring)
        sys.exit(-1) # exit with error (TODO is -1 correct?)

if __name__ == '__main__':
    main()

