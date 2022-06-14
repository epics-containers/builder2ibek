builder2ibek
============

|code_ci| |docs_ci| |coverage| |pypi_version| |license|

IOC Builder for EPICS and Kubernetes:

- In an EPICS support module describe what entities an IOC using it can create,
  what arguments they take, and what database and st.cmd snippets it should
  generate in a ``builder.yaml`` file
- Build support modules together in a container image and use ``builder2ibek`` in the
  image to create a JSON schema of what an IOC using that image can contain
- Write an ``ioc.yaml`` file against that schema listing instances of the
  entities with arguments
- Use ``builder2ibek`` to generate a startup script, database and Helm chart that runs
  up the IOC contained in the image with them

============== ==============================================================
PyPI           ``pip install builder2ibek``
Source code    https://github.com/epics-containers/builder2ibek
Documentation  https://epics-containers.github.io/builder2ibek
Releases       https://github.com/epics-containers/builder2ibek/releases
============== ==============================================================


.. |code_ci| image:: https://github.com/epics-containers/builder2ibek/workflows/Code%20CI/badge.svg?branch=master
    :target: https://github.com/epics-containers/builder2ibek/actions?query=workflow%3A%22Code+CI%22
    :alt: Code CI

.. |docs_ci| image:: https://github.com/epics-containers/builder2ibek/workflows/Docs%20CI/badge.svg?branch=master
    :target: https://github.com/epics-containers/builder2ibek/actions?query=workflow%3A%22Docs+CI%22
    :alt: Docs CI

.. |coverage| image:: https://codecov.io/gh/epics-containers/builder2ibek/branch/master/graph/badge.svg
    :target: https://codecov.io/gh/epics-containers/builder2ibek
    :alt: Test Coverage

.. |pypi_version| image:: https://img.shields.io/pypi/v/builder2ibek.svg
    :target: https://pypi.org/project/builder2ibek
    :alt: Latest PyPI version

.. |license| image:: https://img.shields.io/badge/License-Apache%202.0-blue.svg
    :target: https://opensource.org/licenses/Apache-2.0
    :alt: Apache License

..
    Anything below this line is used when viewing README.rst and will be replaced
    when included in index.rst

See https://epics-containers.github.io/builder2ibek for more detailed documentation.
