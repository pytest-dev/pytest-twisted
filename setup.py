#!/usr/bin/env python

from setuptools import setup

setup(
    name='pytest-twisted',
    version='1.8',
    description='A twisted plugin for py.test.',
    long_description=open('README.rst').read(),
    author='Ralf Schmitt, Kyle Altendorf, Victor Titor',
    author_email='ralf@brainbot.com',
    url='https://github.com/pytest-dev/pytest-twisted',
    py_modules=['pytest_twisted'],
    install_requires=['greenlet', 'pytest>=2.3', 'decorator'],
    classifiers=[
        'Development Status :: 5 - Production/Stable',
        'Intended Audience :: Developers',
        'License :: OSI Approved :: BSD License',
        'Operating System :: OS Independent',
        'Programming Language :: Python',
        'Topic :: Software Development :: Testing',
        'Programming Language :: Python :: 2',
        'Programming Language :: Python :: 2.7',
        'Programming Language :: Python :: 3',
        'Programming Language :: Python :: 3.4',
        'Programming Language :: Python :: 3.5',
        'Programming Language :: Python :: 3.6',
    ],
    entry_points={'pytest11': ['twisted = pytest_twisted']}
)
