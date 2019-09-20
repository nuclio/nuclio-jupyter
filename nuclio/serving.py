serving_footer = r'''

import json
import os
import numpy as np
from typing import List
from http import HTTPStatus
from typing import Dict
from kfserving.protocols.request_handler import \
    RequestHandler  # pylint: disable=no-name-in-module
from enum import Enum

############
# Encoders #
############

class NumpyEncoder(json.JSONEncoder):
    def default(self, obj):  # pylint: disable=arguments-differ,method-hidden
        if isinstance(obj, (
                np.int_, np.intc, np.intp, np.int8, np.int16, np.int32,
                np.int64, np.uint8,
                np.uint16, np.uint32, np.uint64)):
            return int(obj)
        elif isinstance(obj, (np.float_, np.float16, np.float32, np.float64)):
            return float(obj)
        elif isinstance(obj, (np.ndarray,)):
            return obj.tolist()
        return json.JSONEncoder.default(self, obj)

class SeldonPayload(Enum):
    TENSOR = 1
    NDARRAY = 2
    TFTENSOR = 3

def _extract_list(body: Dict) -> List:
    data_def = body["data"]
    if "tensor" in data_def:
        arr = np.array(data_def.get("tensor").get("values")).reshape(
            data_def.get("tensor").get("shape"))
        return arr.tolist()
    elif "ndarray" in data_def:
        return data_def.get("ndarray")
    else:
        raise Exception("Could not extract seldon payload %s" % body)


def _create_seldon_data_def(array: np.array, ty: SeldonPayload):
    datadef = {}
    if ty == SeldonPayload.TENSOR:
        datadef["tensor"] = {
            "shape": array.shape,
            "values": array.ravel().tolist()
        }
    elif ty == SeldonPayload.NDARRAY:
        datadef["ndarray"] = array.tolist()
    elif ty == SeldonPayload.TFTENSOR:
        raise NotImplementedError("Seldon payload %s not supported" % ty)
    else:
        raise Exception("Unknown Seldon payload %s" % ty)
    return datadef


def _get_request_ty(
        request: Dict) -> \
        SeldonPayload:  # pylint: disable=inconsistent-return-statements
    data_def = request["data"]
    if "tensor" in data_def:
        return SeldonPayload.TENSOR
    elif "ndarray" in data_def:
        return SeldonPayload.NDARRAY
    elif "tftensor" in data_def:
        return SeldonPayload.TFTENSOR


def create_request(arr: np.ndarray, ty: SeldonPayload) -> Dict:
    seldon_datadef = _create_seldon_data_def(arr, ty)
    return {"data": seldon_datadef}


class SeldonRequestHandler(RequestHandler):

    def __init__(self, context,
                 request: Dict):  # pylint: disable=useless-super-delegation
        super().__init__(request)
        self.context = context

    def validate(self):
        if not "data" in self.request:
            return self.context.Response(
                body="Expected key \"data\" in request body",
                headers={},
                content_type='text/plain',
                status_code=500)
        ty = _get_request_ty(self.request)
        if not (ty == SeldonPayload.TENSOR or ty == SeldonPayload.NDARRAY):
            return self.context.Response(
                body="\"data\" key should contain either \"tensor\","
                     "\"ndarray\"",
                headers={},
                content_type='text/plain',
                status_code=500)

    def extract_request(self) -> List:
        return _extract_list(self.request)

    def wrap_response(self, response: List) -> Dict:
        arr = np.array(response)
        ty = _get_request_ty(self.request)
        seldon_datadef = _create_seldon_data_def(arr, ty)
        return {"data": seldon_datadef}


class TensorflowRequestHandler(RequestHandler):

    def __init__(self, context,
                 request: Dict):  # pylint: disable=useless-super-delegation
        super().__init__(request)
        self.context = context

    def validate(self):
        if "instances" not in self.request:
            return self.context.Response(
                body="Expected key \"instances\" in request body",
                headers={},
                content_type='text/plain',
                status_code=500)

    def extract_request(self) -> List:
        return self.request["instances"]

    def wrap_response(self, response: List) -> Dict:
        return {"predictions": response}


####################
# Serving function #
####################

# Routes

def predict(context, model_name, request):
    global models
    global protocol

    # Load the requested model
    model = models[model_name]

    # Verify model is loaded (Async)
    if not model.ready:
        model.load()

    # Validate request via protocol
    requestHandler: RequestHandler = protocol(context, request)
    requestHandler.validate()
    request = requestHandler.extract_request()

    # Predict
    results = model.predict(request)

    # Wrap & return response
    response = requestHandler.wrap_response(results)
    return response


def no_path(request):
    context.logger.error(f'Path {path} does not exist')
    return ''


# Router
paths = {
    'predict': predict,
    'explain': '',
    'outlier_detector': '',
    'metrics': '',
}

# Definitions
model_prefix = 'SERVING_MODEL_'
models = {}

# Select messaging protocol
protocols = {
    'tensorflow': TensorflowRequestHandler,
    'seldon': SeldonRequestHandler
}
protocol = protocols[os.environ.get('TRANSPORT_PROTOCOL', 'tensorflow')]


def init_context(context):
    global models
    global model_prefix

    # Initialize models from environment variables
    # Using the {model_prefix}_{model_name} = {model_path} syntax
    model_paths = {k[len(model_prefix):]: v for k, v in os.environ.items() if
                   k.startswith(model_prefix)}

    model_class = os.environ.get('MODEL_CLASS')
    fhandler = globals()[model_class]
    models = {name: fhandler(name=name, model_dir=path) for name, path in
              model_paths.items()}
    context.logger.info(f'Loaded {list(models.keys())}')


def handler(context, event):
    global models
    global paths

    # Load event
    event_body = json.loads(event.body, encoding='utf8')

    # Get route & model from event
    splitted_path = event.path.strip('/').split('/')
    function_path = splitted_path[0] if len(splitted_path) > 0 else ''
    try:
        model_name = splitted_path[1]
    except:
        raise Exception('No model was specified')

    context.logger.info(
        f'Serving uri: {event.path} for route {function_path} '
        f'with {model_name}')

    # Verify route validity
    if not function_path in paths:
        return context.Response(body=f'Path {function_path} does not exist',
                                headers={},
                                content_type='text/plain',
                                status_code=400)
    route = paths.get(function_path, no_path)

    # Verify model exists
    if not model_name in models:
        raise Exception(f'Failed to load model {model_name}')

    # Run model
    return route(context, model_name, event_body)
'''
