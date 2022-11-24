# Copyright 2018 Iguazio
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

try:
    from setuptools import setup
except ImportError:
    from distutils.core import setup


def version():
    with open('nuclio/__init__.py') as fp:
        for line in fp:
            if '__version__' in line:
                _, version = line.split('=')
                return version.replace("'", '').strip()


def load_deps(section):
    """Load dependencies from Pipfile, we can't assume toml is installed"""
    # [packages]
    header = '[{}]'.format(section)
    with open('Pipfile') as fp:
        in_section = False
        for line in fp:
            line = line.strip()
            if not line or line[0] == '#':
                continue

            if line == header:
                in_section = True
                continue

            if line.startswith('['):
                in_section = False
                continue

            if in_section:
                # ipython = ">=6.5"
                i = line.find('=')
                assert i != -1, 'bad dependency - {}'.format(line)
                pkg = line[:i].strip()
                version = line[i+1:].strip().replace('"', '')
                if version == '*':
                    yield pkg
                else:
                    yield '{}{}'.format(pkg, version.replace('"', ''))


with open('README.md') as fp:
    long_desc = fp.read()

install_requires = list(load_deps('packages'))
tests_require = list(load_deps('dev-packages'))


setup(
    name='nuclio-jupyter',
    version=version(),
    description='Convert Jupyter notebook to nuclio',
    long_description=long_desc,
    long_description_content_type='text/markdown',
    author='Miki Tebeka',
    author_email='miki@353solutions.com',
    license='MIT',
    url='https://github.com/nuclio/nuclio-jupyter',
    packages=['nuclio'],
    install_requires=install_requires,
    classifiers=[
        'Development Status :: 4 - Beta',
        'Intended Audience :: Developers',
        'License :: OSI Approved :: Apache Software License',
        'Operating System :: POSIX :: Linux',
        'Operating System :: Microsoft :: Windows',
        'Operating System :: MacOS',
        'Programming Language :: Python :: 3',
        'Programming Language :: Python :: 3.7',
        'Programming Language :: Python :: 3.8',
        'Programming Language :: Python :: 3.9',
        'Programming Language :: Python',
        'Topic :: Software Development :: Libraries :: Python Modules',
        'Topic :: Software Development :: Libraries',
    ],
    setup_requires=['pytest-runner'],
    tests_require=tests_require,
    extras_require={
        # jupyter-server is the new "infrastructure" of jupyter, in the Iguazio Jupyter we're still using an old version
        # which uses the notebook-server. installing jupyter-server there is causing troubles (unwanted upgrade of
        # tornado package, so we're installing jupyter-server only if explictly requested by adding an extra
        "jupyter-server": ["jupyter-server~=1.0"],
    },
    entry_points={
        'nbconvert.exporters': [
            'nuclio=nuclio.export:NuclioExporter',
        ],
        'console_scripts': [
            'nuclio=nuclio.__main__:main',
        ],
    },
    zip_safe=False,
    include_package_data=True,
)
