"""
百度小说搜索器 - Python 实现
使用百度搜索 API 搜索小说信息
"""

import re
import time
import requests
from typing import List, Dict, Optional
from flask import Flask, render_template, request, jsonify
from bs4 import BeautifulSoup
from urllib.parse import quote
import QwenNovelSearcher
import traceback

# 尝试导入 baidusearch（推荐使用，免费无需 API Key）
try:
    from baidusearch.baidusearch import search as baidu_search

    USE_BAIDUSEARCH = True
except ImportError:
    USE_BAIDUSEARCH = False
    print("提示: 安装 baidusearch 可获得更好的搜索体验: pip install baidusearch")

app = Flask(__name__)


class BaiduNovelSearcher:
    """百度小说搜索器"""

    def __init__(self):
        self.session = requests.Session()
        self.session.headers.update({
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
            'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8',
            'Accept-Language': 'zh-CN,zh;q=0.9,en;q=0.8',
        })
        self.qwenNovelSearcher = QwenNovelSearcher.QwenNovelSearcher("sk-5ea7ce86f9db45768b424888bc86bd78")

    def clean_url(self, url: str) -> str:
        """清理 URL 末尾的标点符号"""
        return re.sub(r'[.,;!?)]+$', '', url).strip()

    def extract_author_from_text(self, text: str) -> Optional[str]:
        """从文本中提取作者信息"""
        patterns = [
            r'(?:作者|作者：|作者:)\s*([^\n,，。、；;]+)',
            r'by\s+([^\n,，。、；;]+)',
            r'作\s*者\s*[:：]\s*([^\n,，。]+)',
        ]
        for pattern in patterns:
            match = re.search(pattern, text, re.IGNORECASE)
            if match:
                author = match.group(1).strip()
                if author and len(author) < 30:  # 过滤过长的匹配
                    return author
        return None

    def resolve_baidu_url(self,baidu_url, session=None):
        """
        解析百度跳转链接，获取最终真实 URL
        :param baidu_url: 形如 http://www.baidu.com/link?url=... 的链接
        :param session: requests.Session 对象，可复用连接
        :return: 真实 URL，如果解析失败则返回原链接
        """
        if not baidu_url.startswith('http://www.baidu.com/link?'):
            return baidu_url

        if session is None:
            session = requests.Session()
            session.headers.update({
                'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36'
            })

        try:
            # 发送 GET 请求，allow_redirects=True 是默认值
            resp = session.get(baidu_url, timeout=5, allow_redirects=True)
            # 最终跳转后的 URL
            final_url = resp.url
            return final_url
        except Exception as e:
            print(f"解析百度链接失败: {e}")
            return baidu_url
    def search_via_baidusearch(self, query: str, num_results: int = 20) -> List[Dict]:
        """
        使用 baidusearch 库进行搜索（推荐，免费）
        文档: https://pypi.org/project/baidusearch/
        """
        if not USE_BAIDUSEARCH:
            return []

        results = []
        try:
            # baidusearch 返回格式: [{'title': '...', 'url': '...', 'rank': 1, ...}]
            search_results = baidu_search(query, num_results=num_results)

            for item in search_results:
                url = item.get('url', '')

                if url and not self._is_ad_url(url):
                    # 解析真实 URL
                    real_url = self.resolve_baidu_url(url)
                    results.append({
                        'title': item.get('title', '搜索结果'),
                        'uri': self.clean_url(real_url),
                        'source': '百度搜索'
                    })

            # 避免请求过快被限制
            time.sleep(1.5)

        except Exception as e:
            print(f"baidusearch 搜索失败: {e}")

        return results

    def search_via_requests(self, query: str, num_results: int = 20) -> List[Dict]:
        """
        使用 requests 直接请求百度搜索页面（备选方案）
        注意：这种方法容易被封禁，仅作备选
        """
        results = []
        try:
            url = f"https://www.baidu.com/s?wd={quote(query)}&rn={num_results}"
            response = self.session.get(url, timeout=10)
            response.encoding = 'utf-8'

            soup = BeautifulSoup(response.text, 'html.parser')

            # 解析百度搜索结果
            for item in soup.select('.result, .c-container'):
                title_elem = item.select_one('h3 a')
                if not title_elem:
                    continue

                title = title_elem.get_text(strip=True)
                url = title_elem.get('href', '')

                # 百度搜索结果需要二次跳转，这里获取实际链接
                if url and url.startswith('/url?'):
                    match = re.search(r'q=([^&]+)', url)
                    if match:
                        url = self.clean_url(match.group(1))

                if url and not self._is_ad_url(url):
                    # 解析真实 URL
                    real_url = self.resolve_baidu_url(url)
                    results.append({
                        'title': title,
                        'uri': real_url,
                        'source': '百度搜索'
                    })

            time.sleep(1)

        except Exception as e:
            print(f"requests 搜索失败: {e}")

        return results[:num_results]

    def _is_ad_url(self, url: str) -> bool:
        """判断是否为广告链接"""
        ad_patterns = ['/baidu.php?', 'posid=', 'cpro', 'union']
        return any(pattern in url for pattern in ad_patterns)

    def search_novel(self, novel_name: str, existing_uris: set = None) -> Dict:
        """
        搜索小说信息

        Args:
            novel_name: 小说名称
            existing_uris: 已有的 URL 集合，用于去重

        Returns:
            dict: 包含 author 和 results 的搜索结果
        """
        if existing_uris is None:
            existing_uris = set()

        results = []
        author = None

        # 构建搜索查询
        search_queries = [
            f"{novel_name} 小说",
            f"{novel_name} 在线阅读",
            f"{novel_name} 最新章节",
            f"{novel_name} 小说 作者"
        ]

        for query in search_queries[:2]:  # 先用前两个查询，避免请求过多
            try:
                # 优先使用 baidusearch
                batch_results = self.search_via_baidusearch(query, num_results=15)
                print(f"百度搜索接口：{batch_results}")
                # 如果 baidusearch 不可用，使用 requests 方案
                if not batch_results:
                    batch_results = self.search_via_requests(query, num_results=15)
                    print(f"百度网页搜索：{batch_results}")
                #使用AI大模型搜索
                if not batch_results:
                    res=self.qwenNovelSearcher.search(novel_name)
                    batch_results= res["results"]
                    print(f"阿里AI搜索：{batch_results}")

                for res in batch_results:
                    uri = res['uri']
                    if uri not in existing_uris:
                        existing_uris.add(uri)
                        results.append(res)

                        # 尝试从标题中提取作者
                        if not author:
                            author = self._extract_author_from_title(res['title'], novel_name)

            except Exception as e:
                print(f"百度搜索 '{query}' 失败: {e}")

            time.sleep(1)  # 请求间隔

        return {
            'author': author,
            'results': results,
            'existing_uris': existing_uris
        }

    def _extract_author_from_title(self, title: str, novel_name: str) -> Optional[str]:
        """从标题中提取作者"""
        patterns = [
            rf'{re.escape(novel_name)}[\s_\-]*(?:作者|by)[\s_\-]*([^\s_\-【】]+)',
            r'作者[：:\s]*([^\s【】]{2,12})',
            r'by\s+([^\s]{2,12})',
        ]

        for pattern in patterns:
            match = re.search(pattern, title, re.IGNORECASE)
            if match:
                author = match.group(1).strip()
                if author and len(author) <= 15:
                    return author
        return None

    def search_more(self, novel_name: str, author: str, existing_uris: set) -> List[Dict]:
        """
        加载更多搜索结果

        Args:
            novel_name: 小说名称
            author: 作者名称
            existing_uris: 已有 URL 集合

        Returns:
            list: 新的搜索结果列表
        """
        new_results = []

        # 构建更多搜索查询
        more_queries = [
            f"{novel_name} {author} 小说",
            f"{novel_name} 全文阅读",
            f"{novel_name} 免费阅读",
            f"小说 {novel_name}"
        ]

        for query in more_queries:
            batch_results = self.search_via_baidusearch(query, num_results=10)

            for res in batch_results:
                uri = res['uri']
                if uri not in existing_uris:
                    existing_uris.add(uri)
                    new_results.append(res)

            time.sleep(1.5)

            if len(new_results) >= 15:  # 获取足够多的新结果后停止
                break
        if not new_results:
            res = self.qwenNovelSearcher.search_more(novel_name)
            new_results = res["results"]

        return new_results


# 创建全局搜索器实例
searcher = BaiduNovelSearcher()


# Flask 路由
@app.route('/')
def index():
    """首页"""
    return render_template('index.html')


@app.route('/api/search', methods=['POST'])
def search():
    """搜索 API"""
    data = request.get_json()
    novel_name = data.get('novel_name', '').strip()
    is_load_more = data.get('is_load_more', False)
    existing_uris = set(data.get('existing_uris', []))
    author = data.get('author', '')

    if not novel_name:
        return jsonify({'error': '请输入小说名称'}), 400

    try:
        if is_load_more:
            # 加载更多
            new_results = searcher.search_more(novel_name, author, existing_uris)
            return jsonify({
                'results': new_results,
                'has_more': len(new_results) > 0,
                'message': '没有更多结果了' if len(new_results) == 0 else None
            })
        else:
            # 首次搜索
            result = searcher.search_novel(novel_name, existing_uris)
            return jsonify({
                'novel_name': novel_name,
                'author': result['author'],
                'results': result['results'],
                'existing_uris': list(result['existing_uris'])
            })
    except Exception as e:
        error_info = f"{type(e).__name__}: {str(e)}\n{traceback.format_exc()}"
        print(error_info)
        return jsonify({'error': '搜索过程中出错，请稍后再试'}), 500


if __name__ == '__main__':
    app.run(debug=True, host='0.0.0.0', port=5000)