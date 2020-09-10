from setuptools import setup

with open("README.rst") as f:
    long_description = f.read()

setup(
    name="pytest-twisted",
    version="1.13.1",
    description="A twisted plugin for pytest.",
    long_description=long_description,
    long_description_content_type="text/x-rst",
    author="Ralf Schmitt, Kyle Altendorf, Victor Titor",
    author_email="sda@fstab.net",
    url="https://github.com/pytest-dev/pytest-twisted",
    py_modules=["pytest_twisted"],
    python_requires='>=2.7,!=3.0.*,!=3.1.*,!=3.2.*,!=3.3.*,!=3.4.*',
    install_requires=["greenlet", "pytest>=2.3", "decorator"],
    extras_require={
        "dev": ["pre-commit", "black"],
        "pyside2": ["pyside2", "qt5reactor"],
        "pyqt5": ["pyqt5", "qt5reactor>=0.6.2"],
    },
    classifiers=[
        "Development Status :: 5 - Production/Stable",
        "Intended Audience :: Developers",
        "License :: OSI Approved :: BSD License",
        "Operating System :: OS Independent",
        "Programming Language :: Python",
        "Topic :: Software Development :: Testing",
        "Programming Language :: Python :: 2",
        "Programming Language :: Python :: 2.7",
        "Programming Language :: Python :: 3",
        "Programming Language :: Python :: 3.5",
        "Programming Language :: Python :: 3.6",
        "Programming Language :: Python :: 3.7",
        "Programming Language :: Python :: 3.8",
        "Programming Language :: Python :: Implementation :: CPython",
        "Programming Language :: Python :: Implementation :: PyPy",
    ],
    entry_points={"pytest11": ["twisted = pytest_twisted"]},
)
