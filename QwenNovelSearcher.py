import os
import re
import json
from typing import List, Dict, Optional, Set, Any
from openai import OpenAI



class QwenNovelSearcher:
    """使用阿里云百炼 Qwen 模型进行小说搜索"""

    def __init__(self, api_key: Optional[str] = None, base_url: str = "https://dashscope.aliyuncs.com/compatible-mode/v1"):
        """
        初始化 Qwen 客户端
        :param api_key: 百炼 API Key，默认从环境变量 DASHSCOPE_API_KEY 读取
        :param base_url: 百炼兼容 OpenAI 的接口地址
        """
        self.api_key = api_key or os.getenv()
        if not self.api_key:
            raise ValueError("请设置 DASHSCOPE_API_KEY 环境变量或传入 api_key 参数")

        self.client = OpenAI(
            api_key=self.api_key,
            base_url=base_url,
        )
        # 使用 Qwen-Plus 模型（性能均衡）
        self.model = "qwen-plus"
        self.seen_uris = set()
        self.novel_name = ""
        self.author = ""

    def _clean_url(self, url: str) -> str:
        """清理 URL 末尾的标点符号"""
        return re.sub(r'[.,;!?)]+$', '', url).strip()

    def _extract_urls_from_text(self, text: str) -> List[str]:
        """从 AI 返回的文本中提取所有 URL"""
        # 匹配 http/https 开头的链接，排除末尾标点
        url_regex = r'https?://[^\s<]+[^<.,:;"\')\]\s]'
        urls = re.findall(url_regex, text)
        return [self._clean_url(u) for u in urls]

    def _extract_author_from_text(self, text: str) -> Optional[str]:
        """从 AI 返回的文本中提取作者姓名"""
        patterns = [
            r'(?:作者|作者：|作者:)\s*([^\n,，。、；;]+)',
            r'by\s+([^\n,，。、；;]+)',
            r'作\s*者\s*[:：]\s*([^\n,，。]+)',
        ]
        for pattern in patterns:
            match = re.search(pattern, text, re.IGNORECASE)
            if match:
                author = match.group(1).strip()
                if author and len(author) < 30:
                    return author
        return None

    def _call_qwen(self, prompt: str) -> str:
        """
        调用 Qwen 模型，返回生成的文本
        """
        try:
            completion = self.client.chat.completions.create(
                model=self.model,
                messages=[
                    {"role": "system", "content": "你是一个百度搜索助手，精通中文网络资源查找。请严格按照要求输出结果。"},
                    {"role": "user", "content": prompt},
                ],
                #启用联网搜索
                extra_body={"enable_search": True},
                temperature=0.3,   # 降低随机性，提高准确性
                max_tokens=2048,
            )
            return completion.choices[0].message.content
        except Exception as e:
            print(f"调用 Qwen API 失败: {e}")
            return ""

    def search(self, novel_name: str, is_load_more: bool = False) -> Dict[str, Any]:
        """
        搜索小说信息
        :param novel_name: 小说名称
        :param is_load_more: 是否为加载更多模式
        :return: 包含 author, results, existing_uris 的字典
        """
        self.novel_name = novel_name

        if is_load_more:
            # 构建加载更多的提示词，排除已有 URL
            recent_uris_str = "\n".join(list(self.seen_uris)[-10:])
            prompt = (
                f"你现在是一个百度搜索助手。请继续为小说 '{novel_name}' (作者: {self.author}) 寻找**更多**不同的阅读网址。\n"
                f"**请不要提供以下已经找到的网址：**\n"
                f"{recent_uris_str}\n"
                f"请务必提供指向该小说具体详情页或阅读页的完整 URL 路径。请直接列出新的网址。"
            )
        else:
            # 首次搜索，清空已见 URL
            self.seen_uris.clear()
            prompt = (
                f"你现在是一个百度搜索助手。请专门在百度 (baidu.com) 以及中文小说平台上搜索小说 '{novel_name}'。\n"
                f"1. 识别作者姓名。\n"
                f"2. 找到所有可用的阅读网址（包括正版、社区、网页小说站点等）。\n"
                f"**重要：请务必提供指向该小说具体详情页或阅读页的完整 URL 路径，而不仅仅是网站主页。**\n"
                f"请先提供作者姓名，然后清晰地列出这些直接指向书名的完整网址。"
            )

        # 调用模型
        response_text = self._call_qwen(prompt)
        print(response_text)
        if not response_text:
            return {"author": None, "results": [], "existing_uris": list(self.seen_uris)}

        # 提取作者（仅在首次搜索时更新）
        author = None
        if not is_load_more:
            author = self._extract_author_from_text(response_text)
            if author:
                self.author = author

        # 提取 URL
        urls = self._extract_urls_from_text(response_text)
        new_results = []
        for url in urls:
            if url and url not in self.seen_uris:
                self.seen_uris.add(url)
                # 从 URL 中提取域名作为标题
                try:
                    domain = url.split("//")[-1].split("/")[0]
                except:
                    domain = "小说链接"
                new_results.append({
                    "title": domain,
                    "uri": url,
                    "source": "AI 分析"
                })

        # 如果返回的 URL 数量不足，可尝试二次补充（可选）
        if not is_load_more and len(new_results) == 0:
            print("AI 未返回有效 URL，尝试二次询问...")
            # 可以再次调用模型强调 URL 格式
            fallback_prompt = f"请直接列出小说 '{novel_name}' 的阅读网址，每行一个，不要包含其他文字。"
            fallback_text = self._call_qwen(fallback_prompt)
            fallback_urls = self._extract_urls_from_text(fallback_text)
            for url in fallback_urls:
                if url and url not in self.seen_uris:
                    self.seen_uris.add(url)
                    try:
                        domain = url.split("//")[-1].split("/")[0]
                    except:
                        domain = "小说链接"
                    new_results.append({
                        "title": novel_name,
                        "uri": url,
                        "source": "AI 分析"
                    })

        return {
            "author": author,
            "results": new_results,
            "existing_uris": list(self.seen_uris)
        }

    def search_more(self, novel_name: str) -> List[Dict]:
        """
        加载更多结果（对外包装方法）
        """
        result = self.search(novel_name, is_load_more=True)
        return result


# 使用示例
if __name__ == "__main__":
    searcher = QwenNovelSearcher("DASHSCOPE_API_KEY")
    # 首次搜索
    res = searcher.search("斗破苍穹")
    print("作者:", res["author"])
    for r in res["results"]:
        print(r["title"], r["uri"])

    # 加载更多
    more = searcher.search_more("斗破苍穹")
    for r in more:
        print("更多:", r["title"], r["uri"])
