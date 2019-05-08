# Copyright 2018 Iguazio
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#   http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.
"""Nuclio command line script"""
import sys
from argparse import ArgumentParser
from os import path

from nuclio.utils import DeployError
from nuclio.deploy import (deploy_from_args, delete_func, delete_parser,
                           populate_parser as populate_deploy_parser)


def do_deploy(args):
    try:
        deploy_from_args(args)
    except (DeployError, ValueError) as err:
        raise SystemExit('error: {}'.format(err))


def do_delete(args):
    try:
        delete_func(args.name, args.dashboard_url, args.namespace)
    except (DeployError, ValueError) as err:
        raise SystemExit('error: {}'.format(err))


def main():
    parser = ArgumentParser(prog='nuclio', description=__doc__)
    sub = parser.add_subparsers()

    dp = sub.add_parser('deploy')
    populate_deploy_parser(dp)
    dp.set_defaults(func=do_deploy)

    delp = sub.add_parser('del')
    delete_parser(delp)
    delp.set_defaults(func=do_delete)

    exargs = [path.expandvars(arg) for arg in sys.argv[1:]]
    args = parser.parse_args(exargs)
    try:
        args.func(args)
    except AttributeError as err:
        print('Unrecognized command or error: ', err)
        parser.print_help()


if __name__ == '__main__':
    main()
