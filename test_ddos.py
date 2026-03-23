import requests

for i in range(25):
    r = requests.get("http://localhost:8002/login/google", allow_redirects=False)
    print(i + 1, r.status_code)
