###############
# This flask app has the responsibility of redirecting requests to a target server that consumes them
# it modifies the requests some in flight to try and ensure that additional values can be turned into
# (query) parameters.
###############
import urllib3
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
urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

app = Flask(__name__)

# storage for configuration items
params = {}
fixed = {}
compiled = {}
base_urls = {}
urls = {}
methods = {}

# cache the path -> remote path and path -> found_params mapping
cache = {}
params_cache = {}
fixed_cache = {}
method_cache = {}


# chop the end off of a URL if that end is a slash
def fix(url):
    if url.endswith("/"):
        url = url[0:-1]
    return url


# parse the configuration file
with open("redirect.yml", "r") as ymlfile:
    cfg = load(ymlfile, Loader=Loader)
    for r in cfg['redirects']:
        if 'match' not in r:
            raise Exception("A match must be specified for a redirect instance")
        match = r['match']
        compiled[match] = re.compile(match)
        if 'dynamic' in r:
            params[match] = r['dynamic']
        if 'fixed' in r:
            fixed[match] = r['fixed']
        if 'method' in r:
            methods[match] = r['method']
        if 'base_url' in r and 'url' in r:
            raise Exception("A base_url or a url must be specified, not both (match string: " + match + ")")
        elif 'base_url' in r:
            # we fix the base_url because we are going to concat that later
            base_urls[match] = fix(r['base_url'])
        elif 'url' in r:
            # we do not fix this url because we are giving control of that to the user
            urls[match] = r['url']
        else:
            raise Exception("A base_url or a url must be specified but none found")


# any request (except to the test path) is treated as a single parameter that will
# be proxied to the target base url
@app.route('/', defaults={'path': ''}, methods=['GET', 'PUT', 'POST'])
@app.route('/<path:path>', methods=['GET', 'PUT', 'POST'])
def redirect(path):
    # this is the dict that will store the params that will be sent to the consuming service
    redirected_params = {}
    found_params = {}
    fixed_params = {}

    # get the decoded version of the path for matching
    decoded_path = urllib.parse.unquote(path)
    remote_path = None
    method = request.method

    # add request args first so they can be overwritten
    if request.args:
        for k in request.args:
            redirected_params[k] = request.args[k]

    if path in cache:
        remote_path = cache[path]
        print("cached match '" + path + "' to target " + remote_path)
        if path in found_params:
            found_params = params_cache[path]
        else:
            found_params = {}
        if path in fixed_cache:
            fixed_params = fixed_cache[path]
        else:
            fixed_params = {}
        if path in method_cache:
            method = method_cache[path]
    else:
        # match url
        for url_match in params:
            c = compiled[url_match]
            # use the compiled matcher against the decoded path and the encoded path to prevent surprises
            if c.match(decoded_path) or c.match(path):
                found_params = params[url_match]
                fixed_params = fixed[url_match]
                params_cache[path] = found_params
                fixed_cache[path] = fixed_params
                if path in methods:
                    method_cache[path] = methods[path]
                    method = methods[path]
                if url_match in base_urls:
                    remote_path = base_urls[url_match] + "/" + urllib.parse.quote(decoded_path)
                    print("matching '" + path + "' to base_url + path = " + remote_path)
                    break
                elif url_match in urls:
                    remote_path = urls[url_match]
                    print("matching '" + path + "' to url " + remote_path)
                    break
        if remote_path is not None:
            # update cache
            cache[path] = remote_path

    if not remote_path:
        print("no match found for path: '" + decoded_path + "'")
        return "no match for path", 404

    # if a configured method has leaked through that isn't a real method then use the original method
    if method != 'GET' and method != 'POST' and method != 'PUT':
        method = request.method

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

    # copy fixed params into map
    if fixed_params:
        for k in fixed_params:
            redirected_params[k] = fixed_params[k]

    # log request
    redirected_data = {} if 'GET' == method else request.get_data()
    print("forwarding:", method, remote_path, redirected_params, redirected_data)

    # build out http request, if it is a get request no need to send a payload
    try:
        if 'GET' == method:
            new_request = requests.request(method, remote_path, headers=request.headers, params=redirected_params,
                                           verify=False)
        else:
            new_request = requests.request(method, remote_path, data=redirected_data, headers=request.headers,
                                           params=redirected_params, verify=False)
    except Exception:
        print("failed to contact remote path: '" + remote_path + "'")
        return "error forwarding request to '" + remote_path + "'", 500

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
