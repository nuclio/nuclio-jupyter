# nuclio Jupyter Export

<!--
Uncomment once we enable travis

[![Build Status](https://travis-ci.org/nu/nuclio.svg?branch=master)](https://travis-ci.org/nuclio/nuclio-jupyter) 
-->

[![License](https://img.shields.io/badge/License-Apache%202.0-blue.svg)](https://opensource.org/licenses/Apache-2.0)

Convert Jupyter notebook to Python code that can run as [nuclio](https://nuclio.io/) handler

## Usage

When developing, import `Context` and `Event` from `nucilo` and use it to
generate a mock context and request.

```python
# nuclio: ignore
from nuclio import Context, Event

context = Context()
event = Event(body='Hello Nuclio')
# your code goes here
```

In the cell you'd like to become the handler, added the comment `#
nuclio:handler`. If there's a specific line you'd like to be the returned one -
added `# nuclio:return` at the end of it.

Cells containing `# nuclio: ignore` comment will be commented out in the export
process.

Now choose `File/Download as/Nuclio` in Jupyter notebook

![](doc/menu.png)

Or you can run

```
jupyter nbconvert --to nuclio example.ipynb
```


This will create `example.py` with your code wrapped in handler function and all
cells with `# nuclio: ignore` commented out.

### Example

![](doc/example.png)

Will generate

```python
# coding: utf-8

# In[1]:
def greeting(name):
    return 'Hi ' + name + '. How are you?'

# In[2]:
default_name = 'Dave'

# In[3]:
# # nuclio:ignore
# from nuclio import Context, Event
# context = Context()
# event = Event(body=default_name)

# In[4]:
def handler(context, event):
    # nuclio:handler
    return greeting(event.body)
```

## Try It Out

You can build a docker image and try it out

### Build

    $ docker build -t jupyter-nuclio .

### Run

    $ docker run -p 8888:8888 jupyter-nuclio

Then open your browser at http://localhost:8888 and enter the password `nuclio`
when prompted.


## Developing

We're using [pipenv](https://docs.pipenv.org/) as package manager. To install
dependencies run

    $ pipenv sync -d

To run the tests run
    
    $ pipenv run python -m pytest -v tests

## Licence

Apache 2.0 (see [LICENSE.txt](LICENSE.txt))
