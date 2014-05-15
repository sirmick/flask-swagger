import types, json, re, traceback, inspect
from datetime import datetime
from swagger_ui import SwaggerAPI
import flask
from flask.ext import restful
from flask.ext.restful import reqparse
import werkzeug.exceptions
import werkzeug.wrappers

debug = False

class Unauthorized(werkzeug.exceptions.Unauthorized):
    description = 'Unauthorized'
    def get_headers(self, environ):
        """Get a list of headers."""
        return [('Content-Type', 'text/html'),
            ('WWW-Authenticate', 'Basic realm="Login required"')]

flask.abort.mapping.update({401: Unauthorized})

class SignatureItem(object):
    def __init__(self, name, *args, **kwargs):
        self.name = name
        self.args = args
        self.kwargs = kwargs
        self.required = kwargs.get('required', False)
        self.action = kwargs.get('action', None)
        self.type = kwargs['type']
        self.help = help

class Signature(object):
    def __init__(self, *args, **kwargs):
        self.return_type = None
        self.body_type = None
        self.parser = reqparse.RequestParser(*args, **kwargs)
        self.path_parameters = {}
        self.query_parameters = []
    def path(self, *args, **kwargs):
        item = SignatureItem(*args, **kwargs)
        self.path_parameters[item.name] = item
        return self
    def query(self, *args, **kwargs):
        self.query_parameters.append(SignatureItem(*args, **kwargs))
        return self
    def setup(self):
        for parameter in self.query_parameters:
            self.parser.add_argument(parameter.name, *parameter.args, **parameter.kwargs)
    def returns(self, model):
        self.return_type = model
        return self
    def body(self, klass, unpack=False, variable='body'):
        self.body_unpack = unpack
        self.body_variable = variable
        self.body_type = klass
        return self
    def parse(self):
        result = self.parser.parse_args()
        return result

class MalformSignatureException(StandardError): pass

class ResourceMethod(object):
    def __init__(self, swagger_api, method, name, view_name, url, description, signature, auth, notes, responses):
        self.swagger_api = swagger_api
        self.method = method
        self.url = url
        self.signature = signature
        self.description = description
        self.auth = auth
        self.view_name = view_name
        self.notes = notes
        self.responses = responses
        self.response_methods = []
        for key,value in self.responses.items():
            self.response_methods.append({
                'code': key,
                'message': value
            })
    def flask_url(self):
        swagger_parameters = re.findall('{[^}]*}', self.url)
        swagger_parameters = [parameter[1:-1] for parameter in swagger_parameters]
        url = self.url
        for parameter_name, parameter in self.signature.path_parameters.items():
            if not parameter_name in swagger_parameters: 
                raise MalformSignatureException('%s from signature is not in the URL %s for %s' % (parameter_name, self.url, self.function))
        for parameter_name in swagger_parameters:
            if not parameter_name in self.signature.path_parameters: 
                raise MalformSignatureException('%s from URL %s is not in the signature for %s' % (parameter_name, self.url, self.function))
            parameter = self.signature.path_parameters[parameter_name]
            flask_parameter = '<string:%s>' % (parameter_name)
            if parameter.type in (int, long): flask_parameter = '<int:%s>' % (parameter_name)
            if parameter.type == float: flask_parameter = '<float%s>' % (parameter_name)
            url = url.replace('{%s}' % (parameter_name), flask_parameter)
        return self.swagger_api.url_prefix + url
    def swagger_url(self):
        return self.url
    def setup(self):
        self.signature.setup()
    def __call__(self, function):
        self.function = function
        if type(function) == types.MethodType:
            function.im_func.signature = self.signature
            function.im_func.resource_method = self
        else:
            function.signature = self.signature
            function.resource_method = self
        return function

class Member(object):
    def __init__(self, type=None, required=False):
        self.type = type

class Model(object):
    def __init__(self, model):
        self.model = {}
        self.member_model = {}
        self.required = []
        for key, value in model.items():
            if isinstance(value, Member):
                self.model[key] = value.type
                self.member_model[key] = value
                if value.required: self.required.append(key)
            else: 
                self.member_model[key] = Member(type=value, required=True)
                self.model[key] = value
                self.required.append(key)
    def __call__(self, klass):
        self.klass = klass
        klass.model = self
        return klass
    def objects_from_json(self, values):
        for name, attr_type in self.model.items():
            value = values.get(name)
            values[name] = from_json(attr_type, value)
        return values
    def json_from_object(self, object):
        response = {}
        if isinstance(object, dict):
            for name, attr_type in self.model.items():
                value = None
                if name in object:
                    value = object[name]
                if value == None: response[name] = None
                else: value = to_json(attr_type, value) 
                response[name] = value
        else:
            for name, attr_type in self.model.items():
                value = None
                if hasattr(object, name):
                    value = getattr(object, name)
                if value == None: response[name] = None
                else: value = to_json(attr_type, value) 
                response[name] = value
        return response
    def set_from_json(self, instance, json):
        if json == None: return
        for name, attr_type in self.model.items():
            value = json.get(name)
            setattr(instance, name, from_json(attr_type, value))

def get_swagger_type(t, model=False, basic=False, required=False):
    if model:
        retval = get_swagger_type(t, model=False, required=required)
        if isinstance(t, list):
            return {'type': 'List', 'items':{'$ref':retval[1:-1]}, 'required':required}
        if isinstance(t, dict):
            return {'type': 'Set', 'items':{'$ref':retval[1:-1]}, 'required':required}
        if isinstance(t, tuple):
            return {'type': retval, 'allowableValues':t, 'required':required}
        return {'type': retval, 'required':required}
    def basic_type(ot):
        if not isinstance(ot, type): return type(ot).__name__
        if issubclass(ot, basestring):
            return 'string'
        elif issubclass(ot, datetime):
            return 'Date'
        elif issubclass(ot, float):
            return 'float'
        elif issubclass(ot, bool):
            return 'bool'
        elif issubclass(ot, int):
            return 'int'
        elif issubclass(ot, long):
            return 'int'
        else: return ot.__name__
    if isinstance(t, basestring): return t
    elif isinstance(t, type): return basic_type(t)
    elif isinstance(t, list):
        return '[%s]' % (basic_type(t[0]))
    elif isinstance(t, dict):
        return '{%s}' % (basic_type(t.items()[0]))
    elif isinstance(t, tuple):
        return basic_type(type(t[0]))
    return type(t).__name__

def from_json(t, v, basic=False):
    if v == None: return None
    def from_basic_type(t0, v0):
        if not isinstance(t0, type): return v0
        if issubclass(t0, basestring):
            return v0
        elif issubclass(t0, datetime):
            if isinstance(v0, datetime): return v0
            return datetime.strptime(v0, "%Y-%m-%dT%H:%M:%S" )
        elif issubclass(t0, float):
            if isinstance(v0, float): return v0
            return float(v0)
        elif issubclass(t0, bool):
            if isinstance(v0, bool): return v0
            return bool(v0)
        elif issubclass(t0, int):
            if isinstance(v0, int): return v0
            return int(v0)
        elif issubclass(t0, long):
            if isinstance(v0, long): return v0
            return long(v0)
        elif hasattr(t0, 'model'):
            return t0.model.objects_from_json(v0)
        else: return v0
    if isinstance(t, basestring): return v
    elif isinstance(t, type): return from_basic_type(t, v)
    elif isinstance(t, list): 
        response = []
        for v1 in v: response.append(from_json(t[0], v1))
        return response
    elif isinstance(t, dict): 
        response = {}
        for k1, v1 in v.items(): response[k1] = from_json(t.values()[0], v1)
        return response
    return v

def to_json(t, v, basic=False):
    def from_basic_type(t0, v0):
        if not isinstance(t0, type): return str(v0)
        if issubclass(t0, basestring):
            return v0
        elif issubclass(t0, datetime):
            return v0.strftime("%Y-%m-%dT%H:%M:%S.%f")
        elif issubclass(t0, float):
            return v0
        elif issubclass(t0, bool):
            return v0
        elif issubclass(t0, int):
            return v0
        elif issubclass(t0, long):
            return v0
        elif hasattr(t0, 'model'):
            return t0.model.json_from_object(v0)
        else: return str(v0)
    if isinstance(t, basestring): return str(v)
    elif isinstance(t, type): return from_basic_type(t, v)
    elif isinstance(t, list): 
        response = []
        for v1 in v: response.append(to_json(t[0], v1))
        return response
    elif isinstance(t, dict): 
        response = {}
        for k1, v1 in v.items(): response[k1] = to_json(t.values()[0], v1)
        return response

class Caller(object):
    def __init__(self):
        self.methods = {}
    def __call__(self, *args, **kwargs):
        if debug:
            print '-'*160
            print flask.request
        def call():
            method = flask.request.method.lower()
            assert method in self.methods
            method = self.methods[method]
            try:
                if method.auth: method.auth()
            except:
                traceback.print_exc()
                raise
            arguments = method.signature.parse()
            arguments.update(kwargs)
            if method.signature.body_type:
                if method.signature.body_type != str:
                    try:
                        body = json.loads(flask.request.data)
                    except ValueError, e:
                        flask.abort(400)
                    body = from_json(method.signature.body_type, body)
                    if method.signature.body_unpack: arguments.update(body)
                    else: arguments[method.signature.body_variable] = body
                else:
                    body = flask.request.data
                    arguments[method.signature.body_variable] = body
            argument_list = []
            argument_dict = {}
            function_arg_spec = inspect.getargspec(method.function)
            index = 0
            start = 0
            if type(method.function) == types.MethodType: start = 1
            function_arg_spec_defaults = function_arg_spec.defaults
            if function_arg_spec_defaults == None: function_arg_spec_defaults = []
            remaining = arguments.copy()
            for function_argument in function_arg_spec.args[start:]: 
                if index < len(function_arg_spec.args) - len(function_arg_spec_defaults):
                    if not function_argument in arguments:
                        raise ValueError('Required parameter "%s" is missing' % (function_argument))
                    argument_list.append(arguments[function_argument])
                    del remaining[function_argument]
                else:
                    argument_dict[function_argument] = arguments[function_argument]
                    del remaining[function_argument]
                index += 1
            if function_arg_spec.keywords:
                argument_dict.update(remaining)
            response = method.function(*argument_list, **argument_dict)
            if response == None: return flask.Response()
            if isinstance(response, (flask.Response, werkzeug.wrappers.Response)): 
                return response
            if method.signature.return_type:
                response = to_json(method.signature.return_type, response)
            if isinstance(response, str): return flask.Response(response)
            if isinstance(response, (dict, list, tuple)): return flask.Response(json.dumps(response))
            #if isinstance(response, object): 
            #    if hasattr(type(response), 'model'):
            #        model = type(response).model
            #        return flask.jsonify(model.json_from_object(response))
            return flask.Response(str(response))
        response = call()
        if debug:
            print '-'*160
            print response
            print response.data
            print '='*160
        return response

class RestSwaggerAPI(object):
    def __init__(self, swagger, app, url_prefix=''):
        self.swagger = swagger
        self.app = app
        self.swagger_models = []
        self.urls = {}
        self.url_prefix = url_prefix
        self.apis = {}
        self.view_names = {}
        app.before_request(RestSwaggerAPI.before_request)
    @staticmethod
    def before_request():       
        pass
    def method(self, method, name, view_name, url, description, signature, auth, notes, responses):
        if not name in self.apis: self.apis[name] = []
        if not url in self.urls: self.urls[url] = []
        resource_method = ResourceMethod(self, method,name,view_name,url,description,signature, auth, notes, responses)
        self.urls[url].append(resource_method)
        self.apis[name].append(resource_method)
        return resource_method
    def model(self, model):
        model = Model(model)
        self.swagger_models.append(model)
        return model
    def get(self, name, url, description, signature, auth=None, view_name=None, notes='', responses={}):
        return self.method('get',name, view_name, url, description, signature, auth, notes, responses)
    def post(self, name, url, description, signature, auth=None, view_name=None, notes='', responses={}):
        return self.method('post',name, view_name, url, description, signature, auth, notes, responses)
    def put(self, name, url, description, signature, auth=None, view_name=None, notes='', responses={}):
        return self.method('put',name, view_name, url, description, signature, auth, notes, responses)
    def delete(self, name, url, description, signature, auth=None, view_name=None, notes='', responses={}):
        return self.method('delete',name, view_name, url, description, signature, auth, notes, responses)
    def resource(self, url, signature):
        if not url in self.urls: self.urls[url] = SwaggerResource(self, url)
        resource = SwaggerResource(self, url)
        resource.api = self
        return resource
    def setup(self):
        apis = {}
        models = {}
        for url, resource_methods in self.urls.items():
            caller = Caller()
            methods = []
            for resource_method in resource_methods:
                caller.methods[resource_method.method] = resource_method
                methods.append(resource_method.method.upper())
                resource_method.setup()

            view_name = resource_method.view_name
            if view_name == None: view_name = resource_method.function.__name__
            if view_name in self.view_names:
                i = 0
                while True:
                    vn = view_name + str(i)
                    if not vn in self.view_names: break
                    i += 1
                view_name = vn
            self.view_names[view_name] = True
            self.app.add_url_rule(resource_method.flask_url(), view_name, caller, methods=methods)
        for model in self.swagger_models:
            model_properties = {}
            for item, value in model.model.items():
                required=item in model.required
                model_properties[item] = get_swagger_type(value, model=True, required=required)
            models[model.klass.__name__] = {
                'id': model.klass.__name__,
                'properties': model_properties
            }
        for name, resource_methods in self.apis.items():
            api = SwaggerAPI(self.swagger, '', url_prefix=self.url_prefix)
            api.models = models
            self.swagger.apis[name] = api
            for resource_method in resource_methods:
                parameters = []
                if resource_method.signature.body_type:
                    parameters.append({
                        'description': '',
                        'paramType': 'body',
                        'required': True,
                        'allowMultiple': False,
                        'dataType': get_swagger_type(resource_method.signature.body_type)
                    })
                for parameter_name, parameter in resource_method.signature.path_parameters.items():
                    parameters.append({
                        'name': parameter.name,
                        'description': parameter.name,
                        'paramType': 'path',
                        'required': parameter.required,
                        'allowMultiple': False,
                        'dataType': get_swagger_type(parameter.type)
                    })
                for parameter in resource_method.signature.query_parameters:
                    parameters.append({
                        'name': parameter.name,
                        'description': parameter.name,
                        'paramType': 'query',
                        'required': parameter.required,
                        'allowMultiple': parameter.action == 'append',
                        'dataType': get_swagger_type(parameter.type)
                    })
                resource = {
                    'path': resource_method.url,
                    'description': resource_method.description,
                    'operations': [
                        {
                            'httpMethod': resource_method.method,
                            'nickname': resource_method.function.__name__,
                            'summary': resource_method.description,
                            'parameters': parameters,
                            'notes': resource_method.notes,
                            'responseMessages':resource_method.response_methods,
                            'responseClass':get_swagger_type(resource_method.signature.return_type),
                        }
                    ]
                }
                found = False
                for swagger_api in api.apis:
                    if swagger_api['path'] == resource_method.url:
                        swagger_api['operations'].append(resource['operations'][0])
                        found = True
                        break
                if not found: api.apis.append(resource)