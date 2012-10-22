#!/usr/bin/env python

from setuptools import setup


setup(name='pytest-twisted',
      version='1.1',
      description='A twisted plugin for py.test.',
      long_description=open("README.rst").read(),
      author='Ralf Schmitt',
      author_email='ralf@brainbot.com',
      url='https://github.com/schmir/pytest-twisted',
      packages=['pytest_twisted'],
      install_requires=["greenlet", "pytest"],
      classifiers=['Development Status :: 5 - Production/Stable',
                   'Intended Audience :: Developers',
                   'License :: OSI Approved :: BSD License',
                   'Operating System :: OS Independent',
                   'Programming Language :: Python',
                   'Topic :: Software Development :: Testing'],
      entry_points=dict(pytest11=['twisted = pytest_twisted:_loader']))
