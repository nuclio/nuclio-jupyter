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
import re


def version():
    with open('nuclio/__init__.py') as fp:
        for line in fp:
            if '__version__' in line:
                _, version = line.split('=')
                return version.replace("'", '').strip()


def parse_deps():
    deps = {}  # section -> deps
    pkgs = None  # current section packages
    with open('Pipfile') as fp:
        for line in fp:
            line = re.sub('#.*', '', line)  # Remove comment

            if not line.strip():
                continue

            if pkgs is not None and '[' in line:
                pkgs = None

            if re.search(r'\[(dev-)?packages\]', line):
                name = line[line.find('[')+1:line.find(']')]
                pkgs = deps[name] = []
                continue

            if pkgs is not None:
                pkg, version = [str.strip(val) for val in line.split('=', 1)]
                version = version[1:-1]  # Trim ""
                if version != '*':
                    pkg = '{}{}'.format(pkg, version)
                pkgs.append(pkg)
    return deps


deps = parse_deps()

setup(
    name='nuclio-jupyter',
    version=version(),
    description='Convert Jupyter notebook to nuclio',
    long_description=open('README.md').read(),
    long_description_content_type='text/markdown',
    author='Miki Tebeka',
    author_email='miki@353solutions.com',
    license='MIT',
    url='https://github.com/nuclio/nuclio-jupyter',
    packages=['nuclio'],
    install_requires=deps['packages'],
    classifiers=[
        'Development Status :: 4 - Beta',
        'Intended Audience :: Developers',
        'License :: OSI Approved :: Apache Software License',
        'Operating System :: POSIX :: Linux',
        'Operating System :: Microsoft :: Windows',
        'Operating System :: MacOS',
        'Programming Language :: Python :: 3',
        'Programming Language :: Python :: 3.6',
        'Programming Language :: Python :: 3.7',
        'Programming Language :: Python',
        'Topic :: Software Development :: Libraries :: Python Modules',
        'Topic :: Software Development :: Libraries',
    ],
    setup_requires=['pytest-runner'],
    tests_require=deps['dev-packages'],
    entry_points={
        'nbconvert.exporters': [
            'nuclio=nuclio.export:NuclioExporter',
        ],
    },
    zip_safe=False,
    include_package_data=True,
)
