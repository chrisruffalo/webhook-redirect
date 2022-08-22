###############
# This flask app has the responsibility of redirecting requests to a target server that consumes them
# it modifies the requests some in flight to try and ensure that additional values can be turned into
# (query) parameters.
###############
from flask import Flask, request
from yaml import load
try:
    from yaml import CLoader as Loader
except ImportError:
    from yaml import Loader as Loader
import json
from jsonpath_rw import parse
import re
import urllib.parse
import requests

app = Flask(__name__)

# storage for configuration items
params = {}
compiled = {}
base_urls = {}
urls = {}


# chop the end off of a string if that end is a slash
def fix(url):
    if url.endswith("/"):
        url = url[0:-1]
    return url


# parse the configuration file
with open("redirect.yml", "r") as ymlfile:
    cfg = load(ymlfile, Loader=Loader)
    for r in cfg['redirects']:
        match = r['match']
        params[match] = r['params']
        compiled[match] = re.compile(match)
        if 'base_url' in r and 'url' in r:
            raise Exception("A base_url or a url must be specified, not both (match string: " + match + ")")
        if 'base_url' in r:
            base_urls[match] = fix(r['base_url'])
        if 'url' in r:
            urls[match] = fix(r['url'])


# any request (except to the test path) is treated as a single parameter that will
# be proxied to the target base url
@app.route('/', defaults={'path': ''}, methods=['GET', 'PUT', 'POST'])
@app.route('/<path:path>', methods=['GET', 'PUT', 'POST'])
def redirect(path):
    # this is the dict that will store the params that will be sent to the consuming service
    redirected_params = {}

    # get the decoded version of the path for matching
    decoded_path = urllib.parse.unquote(path)

    # add request args first so they can be overwritten
    if request.args:
        for k in request.args:
            redirected_params[k] = request.args[k]

    # match url
    for url_match in params:
        c = compiled[url_match]
        # use the compiled matcher against the decoded path and the encoded path to prevent surprises
        if c.match(decoded_path) or c.match(path):
            found_params = params[url_match]
            if url_match in base_urls:
                remote_path = base_urls[url_match] + "/" + urllib.parse.quote(decoded_path)
                break
            elif url_match in urls:
                remote_path = urls[url_match]
                break

    if not remote_path:
        print("no match found for path: '" + decoded_path + "'")
        return "no match for path", 404

    # if a payload was provided we need build parameters from the (hopefully json) payload
    if request.method == 'POST' or request.method == 'PUT':
        raw_payload = request.get_data()
        # only try and process the payload if we have one
        if found_params and len(raw_payload) > 0:
            # if a match is found use the jsonpath to populate query parameters that will be passed
            # the consuming endpoint
            for parameter_pair in found_params:
                payload = json.loads(raw_payload)
                param_key = parameter_pair['name']
                param_json_path = parameter_pair['path']
                found_value = parse(param_json_path).find(payload)
                if found_value and found_value[0] and found_value[0].value:
                    redirected_params[param_key] = found_value[0].value

    # log request
    print("forwarding:", request.method, remote_path, request.query_string, request.get_data())

    # build out http request, if it is a get request no need to send a payload
    if 'GET' == request.method:
        new_request = requests.request(request.method, remote_path, headers=request.headers, params=redirected_params)
    else:
        new_request = requests.request(request.method, remote_path, data=request.get_data(), headers=request.headers, params=redirected_params)

    # just return content for now (status code needs to be next)
    return new_request.content, new_request.status_code


# this route is for testing
@app.route('/test/<path:path>', methods=['GET', 'PUT', 'POST'])
def test(path):
    if request.method == 'PUT' or request.method == 'POST':
        print("got:", request.method, request.path, request.query_string, request.get_data())
    else:
        print("got:", request.method, request.path, request.query_string)
    return "ok\n"


if __name__ == '__main__':
    app.run(host='0.0.0.0')
