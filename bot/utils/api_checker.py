import requests
import re

from bs4 import BeautifulSoup

from bot.core.headers import headers
from bot.utils import logger


base_api_url = 'https://api.paws.community/v1'
auth_endpoints = ['user/auth']
endpoints = ['quests/completed', 'quests/claim',
             'referral/my', 'user',
             'quests/list', 'user/leaderboard',
             'user/wallet', 'user/refresh']


def find_js_files(base_url):
    try:
        response = requests.get(base_url)
        response.raise_for_status()
        content = response.text
        soup = BeautifulSoup(content, 'html.parser')
        scripts = soup.find_all('script', src=True)
        app_js_file = None
        index_js_file = None

        for script in scripts:
            if '/pages/_app' in script.attrs.get('src'):
                app_js_file = script['src']
            if 'pages/index' in script.attrs.get('src'):
                index_js_file = script['src']
        return app_js_file, index_js_file
    except requests.RequestException as e:
        logger.warning(f"Error fetching the base URL: {e}")
        return None, None


def get_js_content(js_url):
    try:
        response = requests.get(js_url)
        response.raise_for_status()
        content = response.text
        match = re.findall(r'"(https?://[^"]+)"', content)
        if match:
            return match, content
        else:
            logger.info("Could not find 'api' in the content.")
            return None
    except requests.RequestException as e:
        logger.warning(f"Error fetching the JS file: {e}")
        return None


def is_valid_endpoints():
    base_url = headers['Origin']
    app_js_file, index_js_file = find_js_files(base_url)
    if app_js_file and index_js_file:
        full_url = f"{base_url}{app_js_file}"
        result, content = get_js_content(full_url)
        if not result:
            logger.warning(f"Js code has changed! {full_url}")
            return False
        if base_api_url not in result:
            logger.warning(f"Base URL <lc>{base_api_url}</lc> not found.")
            return False

        for endpoint in auth_endpoints:
            if endpoint not in content:
                logger.warning(f"Auth endpoint <lc>{endpoint}</lc> not found.")
                return None

        full_url = f"{base_url}{index_js_file}"
        result, content = get_js_content(full_url)
        for endpoint in endpoints:
            if endpoint not in content:
                logger.warning(f"Endpoint <lc>{endpoint}</lc> not found.")
                return False
        return True
    else:
        logger.warning("Could not find any main.js format. Dumping page content for inspection:")
        try:
            response = requests.get(base_url)
            print(response.text[:1000])
            return False
        except requests.RequestException as e:
            logger.warning(f"Error fetching the base URL for content dump: {e}")
            return False
