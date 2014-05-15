import os

from flask import Flask
from flask import request, Response, abort, session, send_file, redirect, url_for
from flask import Blueprint, render_template
from flask.ext import restful
from flask_swagger import *
from devops.projects.webapp import *
from swagger_ui import SwaggerUI, Swagger
from flask_swagger import SwaggerAPI
import flaskext.auth
from flaskext.auth import Auth, AuthUser, login_required, login, logout, get_current_user_data, Role, Permission, permission_required
print login

def get_flask_locations(app):
    locations = {}

    def get_route(r):
        nr = ''
        for c in r:
            if c == '<': return nr
            nr += c
        return nr

    def get_static(function):
        if not isinstance(function, types.MethodType): return None
        if not function.__name__ == 'send_static_file': return None
        instance = function.im_self
        if not hasattr(instance, 'static_folder'): return None
        return instance.static_folder

    for rule in app.url_map.iter_rules():
        function = app.view_functions[rule.endpoint]
        static = get_static(function)
        route = get_route(rule.rule)
        if static: locations[route] = static
        else: locations[route] = None
    return locations

def print_locations(app):
    for rule in app.url_map.iter_rules():
        function = app.view_functions[rule.endpoint]
        print rule,function

def run_swagger_app(app, bindings):
    print_locations(app)
    if 'GUNICORN_CLIENT' in os.environ: return
    elif os.environ.get('GUNICORN',None) == '1' :
        return run_gunicorn_wsgi(app, bindings, get_flask_locations(app))
    elif os.environ.get('WSGIREF',None) == '1':
        return run_wsgiref(app, bindings, get_flask_locations(app))
    return run_debug(app, bindings, get_flask_locations(app))