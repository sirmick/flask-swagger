import logging
import os
from flask import jsonify, Blueprint, render_template
from flask.globals import request

logger = logging.getLogger('flask_peewee_swagger')
current_dir = os.path.dirname(__file__)

class SwaggerUI(object):
    """ Adds a flask blueprint for the swagger ajax UI. """

    def __init__(self, app, title='api docs', url_prefix='', blueprint_name='SwaggerUI'):
        super(SwaggerUI, self).__init__()
        self.app_prefix = url_prefix
        self.url_prefix = url_prefix+'/api-docs'
        self.app = app
        self.title = title
        self.blueprint_name = blueprint_name+str(id(self))
        self.blueprint = Blueprint(self.blueprint_name, __name__,
            static_folder=os.path.join(current_dir, 'static'),
            template_folder=os.path.join(current_dir, 'templates'))

    def setup(self):
        self.blueprint.add_url_rule('/', 'index', self.index)
        self.app.register_blueprint(self.blueprint, url_prefix=self.url_prefix)

    def index(self):
        return render_template('swagger-ui.jinja2',
            static_dir='%s/static' % self.url_prefix,
            title=self.title,
            url_prefix=self.app_prefix
        )


class Swagger(object):
    def __init__(self, app, url_prefix='', blueprint_name='Swagger'):
        super(Swagger, self).__init__()
        self.app = app
        self.apis = {}
        self.url_prefix = url_prefix
        self.blueprint_name = blueprint_name+str(id(self))
        self.blueprint = Blueprint(self.blueprint_name, __name__)

    def setup(self):
        self.blueprint.add_url_rule('/resources', 'resources', self.swagger_resources)
        for api_name, api in self.apis.items():
            self.blueprint.add_url_rule('/resources%s/%s' % (api.url_prefix, api_name),
                api_name, api.swagger_resource)
        self.app.register_blueprint(self.blueprint,
            url_prefix='%s/meta' % self.url_prefix)


    def base_uri(self):
        base_uri = request.host_url
        if base_uri.endswith('/'):
            base_uri = base_uri[0:-1]
        return base_uri

    def swagger_resources(self):
        data = {
            'apiVersion': '0.1',
            'swaggerVersion': '1.1',
            'basePath': '%s%s' % (self.base_uri(), self.url_prefix),
            'apis': [{
                'path': '/meta/resources%s/%s' % (api.url_prefix, api_name),
                'description': api.description
            } for api_name, api in self.apis.items()]
        }
        response = jsonify(data)
        response.headers.add('Cache-Control', 'max-age=0')
        return response

class SwaggerAPI(object):
    def __init__(self, name, description, url_prefix=''):
        self.description = description
        self.name = name
        self.apis = []
        self.models = {}
        self.url_prefix = url_prefix

    def base_uri(self):
        base_uri = request.host_url
        if base_uri.endswith('/'):
            base_uri = base_uri[0:-1]
        return base_uri

    def swagger_resource(self):
        """ Details of a specific model resource. """
        data = {
            'apiVersion': '0.1',
            'swaggerVersion': '1.1',
            'basePath': '%s%s' % (self.base_uri(), self.url_prefix),
            'resourcePath': '/meta/%s' % (self.name),
            'apis': self.apis,
            'models': self.models
        }
        response = jsonify(data)
        response.headers.add('Cache-Control', 'max-age=0')
        return response