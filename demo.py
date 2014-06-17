import sys,os, math, traceback

from flask_swagger_app import *

url_prefix = os.environ.get('URL_PREFIX','')
secret_key = os.environ.get('SIGNED_COOKIE_KEY','A0Zr98j/3yX R~XHH!jmN]LWX/,?RT')

app = Flask('test')
swagger_ui = SwaggerUI(app, url_prefix='')
swagger = Swagger(app, url_prefix='')
test_api = RestSwaggerAPI(swagger, app, url_prefix='')

@test_api.model({
    'integer':int,
    'string':str,
    'array':[str],
    })
class TestData(): 
    pass

@test_api.get(
    'Zoocard','/test-api/{path_str}',
    'Get voucher', Signature()
    .path('path_str', type=str, help='A path string')
    .query('query_str', type=str, help='A query string', required=False)
    .body(TestData, variable='input')
    .returns(TestData),
    notes='Test function'
)
def test(path_str, query_str=None, outlet_id=None):
    data = TestData()
    data.integer = 10
    data.string = 'a test'
    data.array = ['an','array']
    return data

test_api.setup()
swagger.setup()
swagger_ui.setup()
app.debug = True
if __name__ == '__main__':
    app.run(host='0.0.0.0')