import requests

s = requests.Session()
try:
    s.post('http://localhost:5000/register', data={'username':'test3','email':'test3@x.com','passwd':'123'})
    s.post('http://localhost:5000/login', data={'email':'test3@x.com', 'passwd':'123'})

    with open('test_cover.jpg', 'rb') as f1, open('test_game.zip', 'rb') as f2:
        files = {'cover': ('test_cover.jpg', f1, 'image/jpeg'), 'game_file': ('test_game.zip', f2, 'application/zip')}
        data = {'title': 'API Test Game 3', 'categories': 'Action', 'description': 'Testing from python'}
        r = s.post('http://localhost:5000/publish', data=data, files=files)

    print("Status:", r.status_code)
    print("Final URL:", r.url)
except Exception as e:
    print("Error:", e)
