#
# Local script to upload blog entries (as markdown files)
# onto my blog site
#

import requests

######## FUNCTIONS ########

def check_status_code(status_code):
    if status_code == 200:
        print("status code 200: request ok")
    elif status_code == 403:
        raise Exception("status code 403: login failed")
    else:
        raise Exception("status code " + status_code + ": discontinuing script")

def upload_file(filename):
    with open(filename, 'rb') as file:
        upload_response = requests.post(URL + '/upload/', headers=HEADERS, files={'uploaded_file': file})
    check_status_code(upload_response)

# TODO: change when uploading website
URL = 'http://192.168.1.242:5000'

# to denote to the server that this request is coming from me specifically
HEADERS = {'user-agent': 'tommy/post-uploader'}

# TODO: change when uploading website
# due to my hosts ability to serve my page over HTTPS, the password
# can be sent in cleartext
PASSWORD = 'secret'

login_payload = {'password': PASSWORD}
login_response = requests.post(URL + '/login/', headers=HEADERS, data=login_payload)

check_status_code(login_response.status_code)
