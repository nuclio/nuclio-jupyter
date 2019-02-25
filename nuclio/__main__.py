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


from argparse import ArgumentParser

from nuclio.deploy import DeployError
from nuclio.deploy import deploy, populate_parser as populate_deploy_parser


def do_deploy(args):
    name = args.notebook.name
    try:
        deploy(name, args.dashboard_url, name=args.name, project=args.project,
               verbose=args.verbose, create_new=args.create_project,
               tmp_dir=args.work_dir, env=args.env)
    except DeployError as err:
        raise SystemExit('error: {}'.format(err))


def main():
    parser = ArgumentParser(prog='nuclio', description=__doc__)
    sub = parser.add_subparsers()
    dp = sub.add_parser('deploy')
    populate_deploy_parser(dp)
    dp.set_defaults(func=do_deploy)

    args = parser.parse_args()
    args.func(args)


if __name__ == '__main__':
    main()
