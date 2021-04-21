#
# Local script to upload blog entries (as markdown files)
# onto my blog site
#

import requests
import argparse

######## GLOBAL VARIABLES ########

# TODO: change when uploading website
URL = 'http://192.168.1.242:5000'

# to denote to the server that this request is coming from me specifically
HEADERS = {'user-agent': 'tommy/post-uploader'}

# TODO: change when uploading website
# due to my hosts ability to serve my page over HTTPS, the password
# can be sent in cleartext
PASSWORD = 'secret'

######## FUNCTIONS ########

def check_status_code(status_code):
    if status_code == 200:
        print("status code 200: login success")
    elif status_code == 201:
        print("status code 201: file uploaded")
    elif status_code == 400:
        print("status code 400: file not uploaded")
    elif status_code == 403:
        raise Exception("status code 403: login failed")
    else:
        raise Exception("status code " + str(status_code) + ": discontinuing script")

def login():
    login_payload = {'password': PASSWORD}
    login_response = requests.post(URL + '/login/', headers=HEADERS, data=login_payload)

    check_status_code(login_response.status_code)

    global SESSION_COOKIE
    SESSION_COOKIE = dict(session=login_response.cookies['session'])

# TODO: add title and published flag to request
def upload_file(filename, title, published=False):
    with open(filename, 'rb') as file:
        files = {'uploaded_file': ('test_file.md', file)}
        upload_payload = {'title': title, 'published': published}
        upload_response = requests.post(URL + '/upload/', headers=HEADERS, cookies=SESSION_COOKIE, files=files, data=upload_payload)
    check_status_code(upload_response.status_code)

######## MAIN CODE ########

parser = argparse.ArgumentParser(description="Upload files as blog entries onto Tom's blog website.")
parser.add_argument("title", help="Specify title for entry.")
parser.add_argument("file", help="Specify file to upload.")

# optional argument that will store value True if called from the command line
parser.add_argument("-p", "--published", help="Specify whether or not the file is ready to be published.", action="store_true")

args = parser.parse_args()

login()

upload_file(args.file, args.title, args.published)
