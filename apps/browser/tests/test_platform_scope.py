"""All shared platforms use the same canonical read scope in Python and Chrome."""

import json
from pathlib import Path
import subprocess
import sys
import unittest

APP = Path(__file__).resolve().parents[1]
sys.path.insert(0,str(APP / 'backend'))
from errors import BrowserValidationError
from platform_scope import platform_url


class PlatformScopeTests(unittest.TestCase):
    def test_platform_routes_aliases_and_queries_match_chrome_policy(self):
        urls = [
            'https://www.instagram.com/name.with.dots/?tracking=1',
            'https://www.instagram.com/explore/search/keyword/?q=hello+world',
            'https://twitter.com/alice/status/123/?tracking=1',
            'https://reddit.com/r/python/comments/abc/title/',
            'https://www.facebook.com/profile.php?id=123',
            'https://www.facebook.com/groups/123/posts/456/',
            'https://www.linkedin.com/search/results/all/?keywords=engineer',
            'https://search.bilibili.com/all/?keyword=hello',
            'https://space.bilibili.com/123/video/',
            'https://www.xiaohongshu.com/search_result/?keyword=hello',
            'https://xueqiu.com/S/SH600000/',
            'https://www.zhipin.com/job_detail/abc.html',
            'https://www.zhipin.com/web/geek/job/?query=engineer&city=100',
            'https://youtu.be/abcdefghijk?search_query=ignored',
            'https://www.youtube.com/watch/?v=abcdefghijk&tracking=1',
            'https://www.xiaoyuzhoufm.com/episode/abc123/',
            'https://www.instagram.com/accounts/login/',
            'https://x.com/messages/',
            'https://www.facebook.com/settings/',
            'https://www.linkedin.com/messaging/',
            'https://www.xiaohongshu.com/%2e%2e/settings/',
            'https://www.instagram.com/name/../direct/',
            'https://xueqiu.com/trade/',
            'https://www.zhipin.com/web/user/login/',
            'https://user:password@www.youtube.com/watch?v=abcdefghijk',
            'https://example.com/',
            'https://www.instagram.com/name/?'+'&'.join('q='+str(i) for i in range(31)),
        ]
        python = []
        for url in urls:
            try: python.append(platform_url(url))
            except BrowserValidationError: python.append(None)
        code = "import {platformUrl} from './companion/scope.mjs';let text='';for await(const c of process.stdin)text+=c;console.log(JSON.stringify(JSON.parse(text).map(u=>{try{return platformUrl(u);}catch{return null;}})));"
        process = subprocess.run(['node','--input-type=module','-e',code],input=json.dumps(urls),text=True,capture_output=True,cwd=APP,timeout=15,check=True)
        self.assertEqual(python,json.loads(process.stdout))
        allowed = set(range(7)) | {13,14}
        self.assertTrue(all(value is not None if i in allowed else value is None for i,value in enumerate(python)))

    def test_a_bound_platform_cannot_switch_to_another_supported_platform(self):
        with self.assertRaises(BrowserValidationError):
            platform_url('https://www.youtube.com/watch?v=abcdefghijk',expected_platform='instagram')


if __name__ == '__main__':
    unittest.main()
