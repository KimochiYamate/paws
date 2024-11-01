import asyncio
import json
import sys
from time import time

import aiohttp
import brotli
from aiohttp_proxy import ProxyConnector
from better_proxy import Proxy
from bot.config import settings

from bot.utils import logger
from bot.exceptions import InvalidSession
from .headers import headers

from random import randint

from ..utils.api_checker import is_valid_endpoints
from ..utils.tg_manager.TGSession import TGSession


class Tapper:
    def __init__(self, tg_session: TGSession):
        self.tg_session = tg_session
        self.session_name = tg_session.session_name
        self.start_param = ''
        self.name = ''

    async def login(self, http_client: aiohttp.ClientSession, tg_web_data: str, retry=0):
        try:
            payload = {'data': tg_web_data}
            if self.tg_session.start_param:
                payload['referralCode'] = self.tg_session.start_param

            response = await http_client.post("https://api.paws.community/v1/user/auth", json=payload,
                                              timeout=aiohttp.ClientTimeout(60))

            response.raise_for_status()
            response_json = await response.json()
            auth_token = None
            if response_json.get('success', False):
                auth_token = response_json.get('data', [])[0]
            return auth_token

        except Exception as error:
            if retry < 5:
                logger.warning(f"{self.session_name} | Can't logging | Retry attempt: {retry}")
                await asyncio.sleep(delay=randint(5, 10))
                return await self.login(http_client, tg_web_data=tg_web_data, retry=retry + 1)

            logger.error(f"{self.session_name} | Unknown error when logging: {error}")
            await asyncio.sleep(delay=randint(3, 7))

    async def check_proxy(self, http_client: aiohttp.ClientSession, proxy: Proxy) -> None:
        try:
            response = await http_client.get(url='https://ipinfo.io/ip', timeout=aiohttp.ClientTimeout(20))
            ip = (await response.text())
            logger.info(f"{self.session_name} | Proxy IP: {ip}")
        except Exception as error:
            logger.error(f"{self.session_name} | Proxy: {proxy} | Error: {error}")

    async def get_all_tasks(self, http_client: aiohttp.ClientSession, retry=0):
        try:
            response = await http_client.get(f"https://api.paws.community/v1/quests/list")
            response.raise_for_status()
            response_bytes = await response.read()
            response_text = brotli.decompress(response_bytes)
            response_json = json.loads(response_text.decode('utf-8'))
            return response_json.get('data', [])
        except Exception as error:
            if retry < 3:
                logger.warning(f"{self.session_name} | Can't getting tasks | Retry attempt: {retry}")
                await asyncio.sleep(delay=randint(5, 10))
                return await self.get_all_tasks(http_client, retry=retry + 1)

            logger.error(f"{self.session_name} | Unknown error when getting tasks: {error}")
            await asyncio.sleep(delay=3)

    async def processing_tasks(self, http_client: aiohttp.ClientSession):
        try:
            tasks = await self.get_all_tasks(http_client)
            if tasks:
                for task in tasks:
                    progress = task['progress']
                    if not progress['claimed'] and task['code'] not in settings.DISABLED_TASKS:
                        result = True if progress['current'] == progress['total'] else None
                        if progress['current'] < progress['total']:
                            if task['code'] == 'telegram':
                                if not settings.JOIN_TG_CHANNELS:
                                    continue
                                url = task['data']
                                logger.info(f"{self.session_name} | Performing TG subscription to <lc>{url}</lc>")
                                await self.tg_session.join_tg_channel(url)
                                result = await self.verify_task(http_client, task['_id'])
                            elif task['code'] == 'invite':
                                counter = task['counter']
                                referrals = await self.get_referrals(http_client)
                                if counter > len(referrals):
                                    continue
                                result = await self.verify_task(http_client, task['_id'])
                            elif task['code'] == 'twitter' or task['code'] == 'linked':
                                logger.info(f"{self.session_name} | Performing <lc>{task['title']}</lc> task")
                                result = await self.verify_task(http_client, task['_id'])
                        if result is not None:
                            await asyncio.sleep(delay=randint(5, 10))
                            is_claimed = await self.claim_task_reward(http_client, task['_id'])
                            if is_claimed:
                                rewards = task['rewards'][0]
                                logger.success(f"{self.session_name} | Task <lc>{task['title']}</lc> completed! | "
                                               f"Reward: <e>+{rewards['amount']}</e> PAWS")
                            else:
                                logger.info(f"{self.session_name} | "
                                            f"Rewards for task <lc>{task['title']}</lc> not claimed")
                        else:
                            logger.info(f"{self.session_name} | Task <lc>{task['title']}</lc> not completed")

                        await asyncio.sleep(delay=randint(5, 10))

        except Exception as error:
            logger.error(f"{self.session_name} | Unknown error when processing tasks: {error}")
            await asyncio.sleep(delay=3)

    async def verify_task(self, http_client: aiohttp.ClientSession, task_id: str, retry=0):
        try:
            payload = {'questId': task_id}
            response = await http_client.post(f'https://api.paws.community/v1/quests/completed',
                                              json=payload, timeout=aiohttp.ClientTimeout(60))
            response.raise_for_status()
            response_json = await response.json()
            status = response_json.get('success', False) and response_json.get('data', False)
            return status

        except Exception as e:
            if retry < 3:
                logger.warning(f"{self.session_name} | Can't verify task | Retry attempt: {retry}")
                await asyncio.sleep(delay=randint(5, 10))
                return await self.verify_task(http_client, task_id, retry=retry + 1)

            logger.error(f"{self.session_name} | Unknown error while verifying task <lc>{task_id}</lc> | Error: {e}")
            await asyncio.sleep(delay=3)

    async def claim_task_reward(self, http_client: aiohttp.ClientSession, task_id: str):
        try:
            payload = {'questId': task_id}
            response = await http_client.post(f'https://api.paws.community/v1/quests/claim',
                                              json=payload, timeout=aiohttp.ClientTimeout(60))
            response.raise_for_status()
            response_json = await response.json()
            status = response_json.get('success', False) or response_json.get('completed', False)
            return status

        except Exception as e:
            logger.error(
                f"{self.session_name} | Unknown error while claim reward for task <lc>{task_id}</lc> | Error: {e}")
            await asyncio.sleep(delay=3)

    async def get_referrals(self, http_client: aiohttp.ClientSession):
        try:
            response = await http_client.get(f'https://api.paws.community/v1/referral/my',
                                             timeout=aiohttp.ClientTimeout(60))
            response.raise_for_status()
            response_json = await response.json()
            return response_json.get('data', [])

        except Exception as e:
            logger.error(f"{self.session_name} | Unknown error while getting referrals | Error: {e}")
            await asyncio.sleep(delay=3)

    async def get_user_info(self, http_client: aiohttp.ClientSession, retry=0):
        try:
            response = await http_client.get('https://api.paws.community/v1/user')
            response.raise_for_status()
            response_bytes = await response.read()
            response_text = brotli.decompress(response_bytes)
            response_json = json.loads(response_text.decode('utf-8'))
            if response_json.get('success', False):
                user_data = response_json.get('data')
                return user_data
            else:
                raise Exception

        except Exception as e:
            if retry < 3:
                logger.warning(f"{self.session_name} | Can't get user info | Retry attempt: {retry}")
                await asyncio.sleep(delay=randint(5, 10))
                return await self.get_user_info(http_client, retry=retry + 1)

            logger.error(f"{self.session_name} | Unknown error while getting user info | Error: {e}")
            await asyncio.sleep(delay=3)

    async def run(self, user_agent: str, proxy: str | None) -> None:
        access_token_created_time = 0
        proxy_conn = ProxyConnector().from_url(proxy) if proxy else None
        headers["User-Agent"] = user_agent

        async with aiohttp.ClientSession(headers=headers, connector=proxy_conn, trust_env=True,
                                         auto_decompress=False) as http_client:
            if proxy:
                await self.check_proxy(http_client=http_client, proxy=proxy)

            token_live_time = randint(3500, 3600)
            while True:
                try:
                    sleep_time = randint(settings.SLEEP_TIME[0], settings.SLEEP_TIME[1])
                    if time() - access_token_created_time >= token_live_time:
                        tg_web_data = await self.tg_session.get_tg_web_data()
                        if tg_web_data is None:
                            continue

                        if not is_valid_endpoints():
                            logger.warning("Detected api change! Stopped the bot for safety | "
                                           "Contact me for update: <lc>https://t.me/DesQwertys</lc>")
                            sys.exit()
                        else:
                            logger.info(f"{self.session_name} | Antidetect: endpoints successfully checked")

                        auth_token = await self.login(http_client=http_client, tg_web_data=tg_web_data)
                        if auth_token is None:
                            token_live_time = 0
                            await asyncio.sleep(randint(100, 180))
                            continue

                        access_token_created_time = time()
                        token_live_time = randint(3500, 3600)

                        http_client.headers['Authorization'] = f'Bearer {auth_token}'
                        user_info = await self.get_user_info(http_client=http_client)
                        balance = user_info['gameData']['balance']
                        logger.info(f"{self.session_name} | Balance: <e>{balance}</e> PAWS")

                        if settings.AUTO_TASK:
                            await asyncio.sleep(delay=randint(5, 10))
                            await self.processing_tasks(http_client=http_client)
                            logger.info(f"{self.session_name} | All available tasks completed")

                    logger.info(f"{self.session_name} | Sleep <y>{round(sleep_time / 60, 1)}</y> min")
                    await asyncio.sleep(delay=sleep_time)

                except InvalidSession as error:
                    raise error

                except Exception as error:
                    logger.error(f"{self.session_name} | Unknown error: {error}")
                    await asyncio.sleep(delay=randint(60, 120))


async def run_tapper(tg_session: TGSession, user_agent: str, proxy: str | None):
    try:
        await Tapper(tg_session=tg_session).run(user_agent=user_agent, proxy=proxy)
    except InvalidSession:
        logger.error(f"{tg_session.session_name} | Invalid Session")
