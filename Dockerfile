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

FROM python:3.7-slim
WORKDIR /nuclio
COPY . .
RUN python setup.py install
RUN jupyter notebook --generate-config
# Password is "nuclio", generated with "from notebook.auth import passwd; passwd()"
RUN echo "c.NotebookApp.password = 'sha1:e43810d15203:2d6c0390b6eb9274061318e60315e2d045970509'" >> ~/.jupyter/jupyter_notebook_config.py

EXPOSE 8888
WORKDIR /code
VOLUME /code
COPY tests/handler.ipynb example.ipynb
CMD jupyter notebook --allow-root --no-browser --ip 0.0.0.0
