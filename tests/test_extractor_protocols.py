import unittest

from src.extractor import infer_format_hint, infer_protocol_hints


class ExtractorProtocolTests(unittest.TestCase):
    def test_primary_protocol_hints(self):
        text = "\n".join([
            "vless://u@example.com:443",
            "vmess://ZXhhbXBsZQ==",
            "trojan://p@example.com:443",
            "ss://YWJjZA==",
            "hy2://p@example.com:443",
        ])
        self.assertEqual(
            infer_protocol_hints(text),
            ["hysteria2", "ss", "trojan", "vless", "vmess"],
        )

    def test_non_target_protocols_are_not_hints(self):
        text = "wireguard://x\ntuic://x\nssr://x"
        self.assertEqual(infer_protocol_hints(text), [])

    def test_format_hints(self):
        self.assertEqual(infer_format_hint("https://example.com/sub.yaml", "proxies:\n"), "clash")
        self.assertEqual(infer_format_hint("https://example.com/config.json", '{"outbounds": []}'), "json")
        self.assertEqual(infer_format_hint("https://example.com/sub", "hysteria2://p@example.com:443"), "uri")


if __name__ == "__main__":
    unittest.main()
