What it takes to add a new reactor:
-----------------------------------

* In ``pytest_twisted.py``

  * Write an ``init_foo_reactor()`` function
  * Add ``'foo': init_foo_reactor,`` to ``reactor_installers`` where the key will be the string to be passed such as ``--reactor=foo``.

* In ``testing/test_basic.py``

  * Add ``test_blockon_in_hook_with_foo()`` decorated by ``@skip_if_reactor_not('foo')``
  * Add ``test_wrong_reactor_with_foo()`` decorated by ``@skip_if_reactor_not('foo')``

* In ``tox.ini``

  * Adjust ``envlist`` to include the ``fooreactor`` factor for the appropriate versions of Python
  * Add conditional ``deps`` for the new reactor such as ``foo: foobar`` to the appropriate test environments
  * Add the conditional assignment ``foo: reactor_option=foo`` to ``setenv`` in the appropriate test environments

* In ``.travis.yml``

  * Consider any extra system packages which may be required
