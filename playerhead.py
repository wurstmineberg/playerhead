#!/usr/bin/env python3
"""Get a Minecraft player's skin for Overviewer.

Usage:
  playerhead [options] [<player>]
  playerhead -h | --help
  playerhead --version

Options:
  -h, --help               Print this message and exit.
  -i, --use-person-id      Save the image with the person's id instead of their Minecraft username.
  -o, --output-dir=<dir>   Path to the directory where the heads will be saved and where Player.png is stored. Defaults to a subdirectory in /var/www/wurstmineberg.de/assets/img/head, depending on --size.
  -p, --from-people-file   Get player names from the people file.
  -q, --quiet              Do not print error messages.
  -s, --size=<pixels>      Resize the head to this width, using the nearest-neighbor algorithm. By default, the head is not resized.
  --full-body              Generate a front-view image of the entire skin, not just the head.
  --height=<pizels>        Resize the head to this height, using the nearest-neighbor algorithm. By default, a height proportional to the width is used.
  --no-hat                 Don't include the overlay layers (hat, jacket, sleeves, pants).
  --people-file=<file>     Deprecated. The --from-people-file option now reads directly from the database.
  --version                Print version info and exit.
  --whitelist              Get player names from the whitelist. May be a new-style JSON whitelist or an old-style plaintext whitelist.
  --whitelist-file=<file>  Path to the server whitelist, used only when --whitelist is present [default: /opt/wurstmineberg/world/wurstmineberg/whitelist.json].
"""

__version__ = '3.0.2'

import sys

from PIL import Image
import base64
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
import time
import traceback
import uuid

def check_nick(player):
    return bool(re.match('[A-Za-z0-9_]{1,16}$', player))

def head(player, *, player_skin=None, hat=True, profile_id=None, error_log=None):
    if error_log is None:
        error_log = sys.stderr
    if player_skin is None:
        player_skin, _ = skin(player, profile_id=profile_id, error_log=error_log)
    with player_skin:
        if hat:
            return Image.alpha_composite(player_skin.crop((8, 8, 16, 16)), player_skin.crop((40, 8, 48, 16)))
        return player_skin.crop((8, 8, 16, 16))

def body(player, *, player_skin=None, model=None, hat=True, profile_id=None, error_log=None):
    if error_log is None:
        error_log = sys.stderr
    if player_skin is None or model is None:
        player_skin, model = skin(player, profile_id=profile_id, error_log=error_log)
    result = Image.new('RGBA', (16, 32))
    result.paste(player_skin.crop((8, 8, 16, 16)), (4, 0)) # head
    result.paste(player_skin.crop((20, 20, 28, 32)), (4, 8)) # body
    result.paste(player_skin.crop((4, 20, 8, 32)), (4, 20)) # right leg
    result.paste(player_skin.crop((44, 20, 47 if model == 'alex' else 48, 32)), (1 if model == 'alex' else 0, 8)) # right arm
    if player_skin.size[1] == 32: # old-style skin
        result.paste(player_skin.crop((4, 20, 8, 32)).transpose(Image.FLIP_LEFT_RIGHT), (8, 20)) # left leg
        result.paste(player_skin.crop((44, 20, 47 if model == 'alex' else 48, 32)).transpose(Image.FLIP_LEFT_RIGHT), (12, 8)) # left arm
    else: # new-style skin
        result.paste(player_skin.crop((20, 52, 24, 64)), (8, 20)) # left leg
        result.paste(player_skin.crop((36, 52, 39 if model == 'alex' else 40, 64)), (12, 8)) # left arm
    with player_skin:
        if hat:
            hat_layer = Image.new('RGBA', (16, 32))
            hat_layer.paste(player_skin.crop((40, 8, 48, 16)), (4, 0)) # hat
            if player_skin.size[1] == 64: # new-style skin
                hat_layer.paste(player_skin.crop((20, 36, 28, 48)), (4, 8)) # jacket
                hat_layer.paste(player_skin.crop((4, 36, 8, 48)), (4, 20)) # right pants leg
                hat_layer.paste(player_skin.crop((44, 36, 47 if model == 'alex' else 48, 48)), (1 if model == 'alex' else 0, 8)) # right sleeve
                hat_layer.paste(player_skin.crop((4, 52, 8, 64)), (8, 20)) # left pants leg
                hat_layer.paste(player_skin.crop((52, 52, 55 if model == 'alex' else 56, 64)), (12, 8)) # left sleeve
            return Image.alpha_composite(result, hat_layer)
        return result

def java_uuid_hash_code(uuid):
    leastSigBits, mostSigBits = struct.unpack('>QQ', uuid.bytes)
    l1 = leastSigBits & 0xFFFFFFFF
    l2 = (leastSigBits & 0xFFFFFFFF00000000) >> 32
    m1 = mostSigBits & 0xFFFFFFFF
    m2 = (mostSigBits & 0xFFFFFFFF00000000) >> 32
    return (l1 ^ l2) ^ (m1 ^ m2)

def retry_request(url, error_log=None, *args, **kwargs):
    if error_log is None:
        error_log = sys.stderr
    response = requests.get(url, *args, **kwargs)
    if response.status_code == 429:
        print('Rate limited, trying again in a second', file=error_log)
        time.sleep(1)
        response = requests.get(url, *args, **kwargs)
        if response.status_code == 429:
            print('Still rate limited, trying again in 10 seconds', file=error_log)
            time.sleep(10)
            response = requests.get(url, *args, **kwargs)
            if response.status_code == 429:
                print('Still rate limited, trying again in a minute', file=error_log)
                time.sleep(60)
                response = requests.get(url, *args, **kwargs)
                if response.status_code == 429:
                    print('Still rate limited, giving up', file=error_log)
    response.raise_for_status()
    return response

def skin(player, *, profile_id=None, error_log=None):
    if error_log is None:
        error_log = sys.stderr
    if profile_id is None:
        response = requests.get('https://api.mojang.com/users/profiles/minecraft/{}'.format(player))
        response.raise_for_status()
        try:
            j = response.json()
        except ValueError:
            print('Failed to decode response: {!r}'.format(response), file=error_log)
            raise
        profile_id = uuid.UUID(j['id'])
    response = retry_request('https://sessionserver.mojang.com/session/minecraft/profile/{}'.format(re.sub('-', '', str(profile_id))), error_log=error_log)
    textures = json.loads(base64.b64decode(response.json()['properties'][0]['value'].encode('utf-8')).decode('utf-8'))['textures']
    if 'SKIN' not in textures:
        # default skin
        profile_hash = java_uuid_hash_code(profile_id)
        if profile_hash % 2 == 0:
            return Image.open('/opt/git/github.com/wurstmineberg/playerhead/master/steve.png'), 'steve'
        else:
            return Image.open('/opt/git/github.com/wurstmineberg/playerhead/master/alex.png'), 'alex'
    response = requests.get(textures['SKIN']['url'], stream=True)
    response.raise_for_status()
    return Image.open(response.raw), 'alex' if textures['SKIN'].get('metadata', {}).get('model') == 'slim' else 'steve'

def write_head(player, *, target_dir=None, width=None, height=None, filename=None, error_log=None, profile_id=None, hat=True, full_body=False):
    try:
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
        if full_body:
            function = body
            if width is None:
                width = 16
            if height is None:
                height = width * 2
        else:
            function = head
            if width is None:
                width = 8
            if height is None:
                height = width
        function(player, hat=hat, profile_id=profile_id, error_log=error_log).resize((width, height)).save(str(target_dir / ((player if filename is None else filename) + '.png')))
    except Exception:
        print('Error writing head for {}'.format(player), file=error_log)
        traceback.print_exc(file=error_log)
        return False
    return True

if __name__ == '__main__':
    arguments = docopt(__doc__, version='playerhead ' + __version__)
    kwargs = {
        'full_body': arguments['--full-body'],
        'hat': not arguments['--no-hat'],
        'target_dir': pathlib.Path('/var/www/wurstmineberg.de/assets/img/head') / (arguments['--size'] or 'default')
    }
    if arguments['--output-dir']:
        kwargs['target_dir'] = pathlib.Path(arguments['--output-dir'])
    if arguments['--size']:
        kwargs['width'] = int(arguments['--size'])
    if arguments['--height']:
        kwargs['height'] = int(arguments['--height'])
    with open('/dev/null', 'a') as dev_null:
        if arguments['--quiet']:
            kwargs['error_log'] = dev_null
        if arguments['--from-people-file']:
            import people

            for wmb_id, person in people.get_people_db().obj_dump(version=3)['people'].items():
                if len(person.get('minecraft', {}).get('nicks', [])) > 0:
                    if arguments['--use-person-id']:
                        kwargs['filename'] = wmb_id
                    if 'uuid' in person['minecraft']:
                        kwargs['profile_id'] = uuid.UUID(person['minecraft']['uuid'])
                    elif 'profile_id' in kwargs:
                        del kwargs['profile_id']
                    if not write_head(person['minecraft']['nicks'][-1], **kwargs):
                        sys.exit(1)
                else:
                    print('No Minecraft nickname specified for person with id ' + person['id'], file=sys.stderr)
        elif arguments['--whitelist']:
            with open(WHITELIST) as whitelist:
                try:
                    whitelist_json = json.load(whitelist)
                except ValueError:
                    # old plaintext whitelist
                    for line in whitelist:
                        if not write_head(line.strip(), **kwargs):
                            sys.exit(1)
                else:
                    # JSON whitelist
                    for player in whitelist_json:
                        if not white_head(player['name'], profile_id=uuid.UUID(player['uuid']), **kwargs):
                            sys.exit(1)
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
                    if not write_head(player, **kwargs):
                        sys.exit(1)
        else:
            if not write_head(arguments['<player>'], **kwargs):
                sys.exit(1)
