import unittest

from src.discovery import GitHubDiscovery


class CandidatePolicyTests(unittest.TestCase):
    def test_accepts_content_endpoints(self):
        accepted = [
            "https://raw.githubusercontent.com/a/b/main/sub.txt",
            "https://raw.githubusercontent.com/a/b/main/all/clash.yaml",
            "https://cdn.jsdelivr.net/gh/a/b@main/configs_base64.txt",
            "https://example.com/subscription",
            "https://example.com/vless/sub",
        ]
        for url in accepted:
            self.assertTrue(GitHubDiscovery.looks_like_subscription_url(url), url)

    def test_rejects_repository_ui_badges_and_assets(self):
        rejected = [
            "https://github.com/a/b",
            "https://github.com/a/b/stargazers",
            "https://github.com/a/b/actions/workflows/aggregate.yml",
            "https://img.shields.io/github/stars/a/b?style=for-the-badge",
            "https://raw.githubusercontent.com/a/b/main/assets/hero.svg",
            "https://raw.githubusercontent.com/a/b/main/archive/all_broken.txt",
            "https://raw.githubusercontent.com/a/b/main",
            "https://a.github.io/Free-v2ray-Configs/",
        ]
        for url in rejected:
            self.assertFalse(GitHubDiscovery.looks_like_subscription_url(url), url)


if __name__ == "__main__":
    unittest.main()
