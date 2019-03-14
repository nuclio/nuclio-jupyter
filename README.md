# Nuclio Function Automation for Python and Jupyter 

[![Build Status](https://travis-ci.org/nuclio/nuclio-jupyter.svg?branch=master)](https://travis-ci.org/nuclio/nuclio-jupyter)
[![License](https://img.shields.io/badge/License-Apache%202.0-blue.svg)](https://opensource.org/licenses/Apache-2.0)

Python package for automatically generating and deploying [nuclio](https://github.com/nuclio/nuclio) 
serverless functions from code, archives or Jupyter notebooks.
Providing a powerful mechanism for automating code and function generation, 
simple debugging, lifecycle management, and native integration into data-science tools.<br>

#### The package provides the following features
* Automatically convert code/files + dependencies (environment, packages configuration, data/files)<br> into nuclio function spec or archive
* Automatically build and deploy nuclio functions (code, spec, or archive) onto a cluster
* Provide native integration into [Jupyter](https://jupyter.org/) IDE (Menu and %magic commands)
* Handle function+spec versioning and archiving against an external object storage (s3, http/s or iguazio)

#### What is nuclio?<br>
nuclio is a high performance serverless platform which runs over docker or kubernetes 
and automate the development, operation, and scaling of code (written in multiple supported languages).
nuclio functions can be triggered via HTTP, popular messaging/streaming protocols, scheduled events, and in batch.
nuclio can run in the cloud as a managed offering, or on any Kubernetes cluster (cloud, on-prem, or edge)<br>
[read more about nuclio ...](https://github.com/nuclio/nuclio) 

#### How does it work?
nuclio take code + [function spec](https://github.com/nuclio/nuclio/blob/master/docs/reference/function-configuration/function-configuration-reference.md) + optional file artifacts and automatically convert them to auto-scaling services over Kubernetes.
the artifacts can be provided as a YAML file (with embedded code), as Dockerfiles, or as archives (Git or Zip).
function spec allow you to [define everything](https://github.com/nuclio/nuclio/blob/master/docs/reference/function-configuration/function-configuration-reference.md) from CPU/Mem/GPU requirements, package dependencies, environment variables, secrets, shared volumes, API gateway config, and more.<br>

this package is trying to simplify the configuration and deployment through more abstract APIs and `%nuclio` magic commands which eventually build the code + spec artifacts in YAML or Archive formats 
(archives are best used when additional files need to be packaged or for version control)
## Usage
* [Installing](#installing) 
* [Creating and debugging functions inside a notebook using `%nuclio` magic](#creating-and-debugging-functions-using-nuclio-magic)
* [Exporting functions using Jupyter UI](#creating-and-debugging-functions-using-nuclio-magic)
* [Exporting/importing functions to/from local or cloud storage](#exportingimporting-functions-tofrom-local-or-cloud-storage)
* [Creating and deploying functions using the python API](#creating-and-deploying-functions-using-the-python-api)
* [Controlling function code and configuration](#controlling-function-code-and-configuration):
  * `%nuclio config` - resources, spec, and triggers configuration 
  * `%nuclio cmd` - defining package dependencies 
  * `%nuclio env` and `env_file` - configuring local and remote env variables
  * `%nuclio mount` - mounting shared volumes into a function
  * `%nuclio deploy` - deploy functions onto the cluster
  * `%nuclio show` - show generated function code and spec (YAML)
  * `%nuclio handler` - function handler wrapper
* [Advanced topics](#advanced-topics) 
  * nuclio `init_context()` hook for initializing resources (across invocations)
  * changing `context.logger` verbosity level to DEBUG
  * using Docker
* [Links](#links)
* [Developing](#developing) 
* [Licence](#licence)

## Installing

    pip install  --upgrade nuclio-jupyter

Install in a Jupyter Notebook by running the following in a cell

```
# nuclio: ignore
!pip install --upgrade nuclio-jupyter
```

to access the library use `import nuclio`

## Creating and debugging functions using `%nuclio` magic 
`%nuclio` magic commands and some comment notations (e.g. `# nuclio: ignore`) 
help us provide non-intrusive hints as to how we want to convert the notebook into a full function + spec.
cells which we do not plan to include in the final function (e.g. prints, plots, debug code, etc.) are prefixed with `# nuclio: ignore`
if we want settings such as environment variables and package installations to automatically appear in the fucntion spec 
we use the `env` or `cmd` commands and those will copy them self into the function spec.<br>

after we finish writing the code we can simulate the code with the built-in nuclio `context` object
(see: debugging functions)and when we are done we can use the `export` command to generate the function YAML/archive 
or use `deploy` to automatically deploy the function on a nuclio/kubernetes cluster.  

we can use other commands like `show` to print out the generated function + spec, 
`config` to set various spec params (like cpu/mem/gpu requirements, triggers, etc.), 
and `mount` to auto-mount shared volumes into the function.<br>

for more details use the `%nuclio help` or `%nuclio help <command>`.
  
#### Example:

Can see the following example for configuring resources, writing and testing code, 
deploying the function, and testing the final function.
note serverless functions have an entry point (`handler`) which is called by the run time engine and triggers. 
the handler carry two objects, a `context` (run-time objects like logger) and `event` 
(the body and other attributes delivered by the client or trigger).

We start with, import `nucilo` package, this initialize the `%nuclio` magic commands and `context` object
this section should not be copied to the function so we mark this cell with `# nuclio: ignore`.


```python
# nuclio: ignore
import nuclio
```

the following sections set an environment variable, install desired package, 
and set some special configuration (e.g. set the base docker image used for the function).
note the environment variables and packages will be deployed in the notebook AND in the function, 
we can specify that we are interested in having them only locally (`-l`) or in nuclio spec (`-c`).
we can use local environment variables in those commands with `${VAR_NAME}`, see `help` for details.
>note: `%` is used for single line commands and `%%` means the command apply to the entire cell, see [details](#controlling-function-code-and-configuration) 

```
%nuclio cmd pip install textblob
%nuclio env TO_LANG=fr
%nuclio config spec.build.baseImage = "python:3.6-jessie"
```

In the cell you'd like to become the handler, you can use one of two ways:
* create a `def handler(context, event)` function (the traditional nuclio way)
* or mark a cell with `%%nuclio handler` which means this cell is the handler function (the Jupyter way)

when using the 2nd approach we mark the return line using `# nuclio:return` at the end of it.

we can use the nuclio `context` and `Event` objects to simulate our functions,
once we are done we use the `%nuclio deploy` command to run it on a real cluster, 
note the deploy command return a valid HTTP end-point which we can use to test/use our real function.

Cells containing `# nuclio: ignore` comment will be omitted in the export
process.

#### Example Notebook: 

![](docs/nb-example2.png)

<b>visit [this link](docs/nlp-example.ipynb) to see the complete notebook<b>, 
or check out this [other example](docs/nuclio-example.ipynb)

The generated function spec for the above notebook will look like:

```yaml
apiVersion: nuclio.io/v1
kind: Function
metadata:
  name: nuclio-example
spec:
  build:
    baseImage: python:3.6-jessie
    commands:
    - pip install requests
    - apt-get update && apt-get install -y wget
    noBaseImagesPull: true
  env:
  - name: USER
    value: john
  - name: VERSION
    value: '1.0'
  - name: PASSWORD
    value: t0ps3cr3t
  handler: handler:handler
  runtime: python:3.6
```

## Exporting functions using Jupyter UI
in many cases we just want to export the function into a YAML/Zip file and loaded manually to nuclio (e.g. via nuclio UI).
this package automatically register it self as a Jupyter converter, which allow exporting a notebook into nuclio format,
see example below, choose `File/Download as/Nuclio` in Jupyter notebook 
> Note: you might need to mark the notebook as `Trusted` in order for the Nuclio option to show

![](docs/menu.png)

Or you can run

```
jupyter nbconvert --to nuclio example.ipynb
```

This will create `example.yaml` or `example.zip` (if the function include extra files) with your code, spec, and extra files.

We currently don't support [Google Colaboratory][colab], [Kaggle Notebooks][kaggle] and other custom Jupyter versions.

[colab]: https://colab.research.google.com
[dashboard]: https://nuclio.io/docs/latest/introduction/#dashboard
[kaggle]: https://www.kaggle.com/kernels
## Exporting/importing functions to/from local or cloud storage
nuclio functions are a great way to provide well defined code + dependencies + environment definitions,
functions can be versioned, archived, and restored by simply storing and re-applying their artifacts.

after we defined a functions using the `%nuclio` magic commands or directly from the API, we can `export` them,
we can also use the `archive` command to pack multiple files in the same `zip` archive with the code and spec,
store it locally or upload the archive to cloud storage using a single command.<br>

when we want to deploy the function, we use the `deploy` command or API, just specify the 
archive as the source (vs the code or notebook)

we currently support the following archive options:<br>
local/shared file system, http(s) unauthenticated or with Basic auth, Github, AWS S3, and iguazio PaaS
> note: that at this point nuclio doesnt support pulling archives directly from secret protected S3 buckets  

for AWS S3 the url path convention is `s3://bucket-name/path/to/key.zip`, the access and secret keys should be set 
[the standard boto3 way](https://boto3.amazonaws.com/v1/documentation/api/latest/guide/configuration.html) or using the `-k` and `-s` flags.

example:

specify additional files to pack with the function (will force the use of `zip`)
```python
%nuclio archive -f model.json -f mylib.py
```
convert the current notebook into a function archive and upload into remote object store 
```python
%nuclio export -t https://v3io-webapi:8081/projects -k ${V3IO_ACCESS_KEY}
``` 
deploy and older version from an archive and name it `oldfunc`
```python
%nuclio deploy https://v3io-webapi:8081/projects/myfunc-v1.zip -n oldfunc -k ${V3IO_ACCESS_KEY}
``` 

> note: `export` and `deploy` commands dont have to run from the same notebook, see `help` for detailed command options. 

## Creating and deploying functions using the python API
in some cases working from a notebook is an overkill, or we may want to generate code and configurations programmatically,
the `nuclio` package provide two main function calls `deploy_code` and `deploy_file` which allow us direct access as shown below:

```python
import requests
import nuclio

# define my function code template
code='''
import glob
def handler(context, event):
    context.logger.info('{}')
    return str(glob.glob('/data/*'))
'''

# substitute a string in the template 
code = code.format('Hello World!')
# define a file share (mount my shared fs home dir into the function /data dir)
vol = Volume('data','~/')

# deploy my code with extra configuration (env vars, mount)
addr = nuclio.deploy_code(code,name='myfunc',project='proj',verbose=True, create_new=True, env=['XXX=1234'], mount=vol)

# invoke the generated function 
resp = requests.get(addr)
print(resp.text)

```

the `deploy_file` API allow deploying functions from files or archives 

## Controlling function code and configuration

### config

Set function configuration value (resources, triggers, build, etc.).
Values need to numeric, strings, or json strings (1, "debug", 3.3, {..})
You can use += to append values to a list.

see the [nuclio configuration reference](https://github.com/nuclio/nuclio/blob/master/docs/reference/function-configuration/function-configuration-reference.md)

    Example:
    In [1] %nuclio config spec.maxReplicas = 5
    In [2]: %%nuclio config
    ...: spec.maxReplicas = 5
    ...: spec.runtime = "python2.7"
    ...: build.commands +=  "apk --update --no-cache add ca-certificates"

### cmd

Run a command, add it to "build.Commands" in exported configuration.

    Examples:
    In [1]: %nuclio cmd pip install chardet==1.0.1

    In [2]: %%nuclio cmd
    ...: apt-get install -y libyaml-dev
    ...: pip install pyyaml==3.13

If you'd like to only to add the instructions to function.yaml without
running it locally, use the '--config-only' or '-c' flag

    In [3]: %nuclio cmd --config-only apt-get install -y libyaml-dev
    
### env  

Set environment variable. Will update "spec.env" in configuration.

    Examples:
    In [1]: %nuclio env USER=iguzaio
    %nuclio: setting 'iguazio' environment variable

    In [2]: %%nuclio env
    ...: USER=iguazio
    ...: PASSWORD=t0ps3cr3t
    ...:
    ...:
    %nuclio: setting 'USER' environment variable
    %nuclio: setting 'PASSWORD' environment variable

If you'd like to only to add the instructions to function.yaml without
running it locally, use the '--config-only' or '-c' flag

    In [3]: %nuclio env --config-only MODEL_DIR=/home

If you'd like to only run locally and not to add the instructions to
function.yaml, use the '--local-only' or '-l' flag

### env_file

Set environment from file(s). Will update "spec.env" in configuration.

    Examples:
    In [1]: %nuclio env_file env.yml

    In [2]: %%nuclio env_file
    ...: env.yml
    ...: dev-env.yml
    
### mount
Mount a shared file Volume into the function.

    Example:
    In [1]: %nuclio mount /data /projects/netops/data
    mounting volume path /projects/netops/data as /data
    
### deploy
Deploy notebook/file with configuration as nuclio function.

    %nuclio deploy [file-path|url] [options]

    parameters:
        -n, --name            override function name
        -p, --project         project name (required)
        -d, --dashboard-url   nuclio dashboard url 
        -t, --target-dir      target dir/url for .zip or .yaml files 
        -e, --env             add/override environment variable (key=value)
        -k, --key             authentication/access key for remote archive 
        -u, --username        username for authentication
        -s, --secret          secret-key/password for authentication
        -c, --create-project  create project if not found
        -v, --verbose         emit more logs

    Examples:
    In [1]: %nuclio deploy
    %nuclio: function deployed -p faces

    In [2] %nuclio deploy -d http://localhost:8080 -p tango
    %nuclio: function deployed

    In [3] %nuclio deploy myfunc.py -n new-name -p faces -c
    %nuclio: function deployed
### show
Print out the function code and spec (YAML).
You should save the notebook before calling this function.

### handler
Mark this cell as handler function. You can give optional name

    %%nuclio handler
    context.logger.info('handler called')
    # nuclio:return
    'Hello ' + event.body

    Will become

    def handler(context, event):
        context.logger.info('handler called')
        # nuclio:return
        return 'Hello ' + event.body
        
## Advanced topics

### nuclio `init_context()` hook for initializing resources (across invocations)

TBD

### changing `context.logger` verbosity level to DEBUG
by default the built-in context object is set to print logs at INFO level and above,
if we want to print out the debug level logs we can type the following 

    nuclio.context.set_logger_level(True)
    
this logging level only apply to the notebook/emulation, to change the function runtime 
log level you should use the `config` or nuclio UI.

### using Docker

You can build a docker image and try it out

#### Build

    $ docker build -t jupyter-nuclio .

#### Run

    $ docker run -p 8888:8888 jupyter-nuclio

Then open your browser at http://localhost:8888

## Links

TBD

## Developing

We're using [pipenv](https://docs.pipenv.org/) as package manager. To install
dependencies run

    $ pipenv sync -d

To run the tests run
    
    $ pipenv run python -m pytest -v tests

To upload to pypi either run `make upload` after changing version in
`nuclio/__init__.py` or `python cut_release <version>`. The latter will update
the version in `nuclio/__init__.py`. You can use `+` for the next version. Ask
around for pypi credentials.

## Licence

Apache 2.0 (see [LICENSE.txt](LICENSE.txt))
