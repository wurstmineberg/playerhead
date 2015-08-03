#!/usr/bin/env python3
"""Get a Minecraft player's skin for Overviewer.

Usage:
  playerhead [options] [<player>]
  playerhead -h | --help
  playerhead --version

Options:
  -h, --help               Print this message and exit.
  -i, --use-person-id      Save the image with the person's id instead of their Minecraft username.
  -q, --quiet              Do not print error messages.
  -o, --output-dir=<dir>   Path to the directory where the heads will be saved and where Player.png is stored. Defaults to a subdirectory in /var/www/wurstmineberg.de/assets/img/head, depending on --size.
  -s, --size=<pixels>      Resize the head to this width and height, using the nearest-neighbor algorithm [default: 8].
  --from-people-file       Get player names from the people file.
  --no-hat                 Don't include the hat layer.
  --people-file=<file>     Path to the people file, used only when --from-people-file is present [default: /opt/wurstmineberg/config/people.json].
  --version                Print version info and exit.
  --whitelist              Get player names from the whitelist. May be a new-style JSON whitelist or an old-style plaintext whitelist.
  --whitelist-file=<file>  Path to the server whitelist, used only when --whitelist is present [default: /opt/wurstmineberg/world/wurstmineberg/whitelist.json].
"""

__version__ = '3.0.0'

import sys

from PIL import Image
from docopt import docopt
import io
import json
import os
import pathlib
import re
import requests
import shutil
import struct
import subprocess
import sys
import uuid

def check_nick(player):
    return bool(re.match('[A-Za-z0-9_]{1,16}$', player))

def head(player, hat=True, profile_id=None):
    player_skin = skin(player, profile_id=profile_id)
    if hat:
        return Image.alpha_composite(player_skin.crop((8, 8, 16, 16)), player_skin.crop((40, 8, 48, 16)))
    return player_skin.crop((8, 8, 16, 16))

def java_uuid_hash_code(uuid):
    leastSigBits, mostSigBits = struct.unpack('>QQ', uuid.bytes)
    l1 = leastSigBits & 0xFFFFFFFF
    l2 = (leastSigBits & 0xFFFFFFFF00000000) >> 32
    m1 = mostSigBits & 0xFFFFFFFF
    m2 = (mostSigBits & 0xFFFFFFFF00000000) >> 32
    return (l1 ^ l2) ^ (m1 ^ m2)

def skin(player, profile_id=None):
    request = requests.get('http://skins.minecraft.net/MinecraftSkins/' + player + '.png') #TODO get skin by UUID if given
    try:
        request.raise_for_status()
    except requests.exceptions.HTTPError:
        if profile_id is None:
            #FROM https://gist.github.com/gschizas/678132e045681395eafa
            profile_info = requests.get('https://api.mojang.com/users/profiles/minecraft/' + player).json()
            profile_id = uuid.UUID(profile_info['id'])
        profile_hash = java_uuid_hash_code(profile_id)
        if profile_hash % 2 == 0:
            return Image.open('/var/www/wurstmineberg.de/assets/img/head/steve.png')
        else:
            return Image.open('/var/www/wurstmineberg.de/assets/img/head/alex.png')
    return Image.open(io.BytesIO(request.content))

def write_head(player, target_dir=None, size=8, filename=None, error_log=None, profile_id=None, hat=True):
    if target_dir is None:
        target_dir = pathlib.Path()
    if isinstance(target_dir, str):
        target_dir = pathlib.Path(target_dir)
    if error_log is None:
        error_log = sys.stderr
    if not check_nick(player):
        print('Invalid player name: ' + player, file=error_log)
        return False
    if not target_dir.exists():
        target_dir.mkdir(parents=True)
    head(player, hat=hat, profile_id=profile_id).resize((size, size)).save(str(target_dir / ((player if filename is None else filename) + '.png')))
    return True

if __name__ == '__main__':
    arguments = docopt(__doc__, version='playerhead ' + __version__)
    kwargs = {
        'hat': not arguments['--no-hat'],
        'size': int(arguments['--size']),
        'target_dir': arguments['--output-dir'] or pathlib.Path('/var/www/wurstmineberg.de/assets/img/head') / arguments['--size']
    }
    with open('/dev/null', 'a') as dev_null:
        if arguments['--quiet']:
            kwargs['error_log'] = dev_null
        if arguments['--from-people-file']:
            with open(arguments['--people-file']) as people:
                for person in json.load(people)['people']:
                    if 'minecraft' in person:
                        if arguments['--use-person-id']:
                            kwargs['filename'] = person['id']
                        if 'minecraftUUID' in person:
                            kwargs['profile_id'] = uuid.UUID(person['minecraftUUID'])
                        write_head(person['minecraft'], **kwargs)
                    else:
                        print('No Minecraft nickname specified for person with id ' + person['id'], file=sys.stderr)
        elif arguments['--whitelist']:
            with open(WHITELIST) as whitelist:
                try:
                    whitelist_json = json.load(whitelist)
                except ValueError:
                    # old plaintext whitelist
                    for line in whitelist:
                        write_head(line.strip(), **kwargs)
                else:
                    # JSON whitelist
                    for player in whitelist_json:
                        white_head(player['name'], profile_id=uuid.UUID(player['uuid']), **kwargs)
        elif arguments['<player>'] is None:
            prompt = 'playerhead> ' if sys.stdin.isatty else ''
            while True:
                try:
                    player = input(prompt)
                except KeyboardInterrupt:
                    break
                except EOFError:
                    break
                else:
                    write_head(player, **kwargs)
        else:
            write_head(arguments['<player>'], **kwargs)
