#!/usr/bin/env python

import setuptools

setuptools.setup(
    name='playerhead',
    description='Python script which generates image files from Minecraft player heads',
    author='Wurstmineberg',
    author_email='mail@wurstmineberg.de',
    packages=['playerhead'],
    package_data={'playerhead': ['alex.png', 'steve.png']},
    install_requires=[
        'Pillow',
        'docopt',
        'people',
        'requests'
    ],
    dependency_links=[
        'git+https://github.com/wurstmineberg/people.git#egg=people'
    ]
)
