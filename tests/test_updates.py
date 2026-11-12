"""Tests for the release check; nothing here touches the network."""

from __future__ import annotations

import json
import unittest

from repopull.updates import (
    API_URL,
    Release,
    UpdateError,
    Version,
    is_newer,
    latest_release,
    parse_version,
)


def payload(
    tag: str = "v0.8.0",
    *,
    body: str = "Notes",
    assets: object = None,
    published: str = "2026-11-20T12:00:00Z",
) -> bytes:
    if assets is None:
        assets = [
            {
                "name": "repopull-0.8.0-x86_64.AppImage.zsync",
                "browser_download_url": "https://example.invalid/x.zsync",
            },
            {
                "name": "repopull-0.8.0-x86_64.AppImage",
                "browser_download_url": "https://example.invalid/x.AppImage",
            },
        ]
    return json.dumps(
        {
            "tag_name": tag,
            "html_url": f"https://example.invalid/tag/{tag}",
            "body": body,
            "published_at": published,
            "assets": assets,
        }
    ).encode("utf-8")


class VersionTests(unittest.TestCase):
    def test_parse_accepts_the_forms_we_tag(self) -> None:
        cases = {
            "0.7.0": Version(0, 7, 0),
            "v0.7.0": Version(0, 7, 0),
            "v0.8.0-rc1": Version(0, 8, 0, 1),
            "0.8.0rc2": Version(0, 8, 0, 2),
            "  v1.10.3 ": Version(1, 10, 3),
        }
        for text, expected in cases.items():
            with self.subTest(text=text):
                self.assertEqual(parse_version(text), expected)

    def test_parse_rejects_anything_else(self) -> None:
        for text in ("", "v0.8", "0.8.0.1", "latest", "v0.8.0-beta", "v"):
            with self.subTest(text=text):
                self.assertIsNone(parse_version(text))

    def test_prereleases_sort_below_the_release_they_precede(self) -> None:
        rc1 = parse_version("v0.8.0-rc1")
        rc2 = parse_version("v0.8.0-rc2")
        final = parse_version("v0.8.0")
        assert rc1 is not None and rc2 is not None and final is not None
        next_patch = parse_version("v0.8.1")
        assert next_patch is not None
        self.assertLess(rc1.key, rc2.key)
        self.assertLess(rc2.key, final.key)
        self.assertLess(final.key, next_patch.key)

    def test_str_round_trips(self) -> None:
        self.assertEqual(str(Version(0, 8, 0)), "0.8.0")
        self.assertEqual(str(Version(0, 8, 0, 3)), "0.8.0rc3")


class ReleaseTests(unittest.TestCase):
    def test_newer_release_is_reported(self) -> None:
        release = latest_release(lambda _url: payload("v0.8.0"))
        self.assertTrue(is_newer(release, "0.7.0"))
        self.assertFalse(is_newer(release, "0.8.0"))
        self.assertFalse(is_newer(release, "0.9.0"))

    def test_fields_are_read_from_the_payload(self) -> None:
        release = latest_release(lambda _url: payload(body="Hello"))
        self.assertEqual(release.version, Version(0, 8, 0))
        self.assertEqual(release.tag, "v0.8.0")
        self.assertEqual(release.page, "https://example.invalid/tag/v0.8.0")
        self.assertEqual(release.notes, "Hello")
        self.assertEqual(release.published, "2026-11-20T12:00:00Z")
        self.assertEqual(release.asset, "repopull-0.8.0-x86_64.AppImage")
        self.assertEqual(release.download, "https://example.invalid/x.AppImage")

    def test_a_release_without_an_appimage_still_checks(self) -> None:
        release = latest_release(lambda _url: payload(assets=[]))
        self.assertIsNone(release.asset)
        self.assertIsNone(release.download)

    def test_the_api_url_is_the_repository_release_endpoint(self) -> None:
        seen: list[str] = []

        def fetch(url: str) -> bytes:
            seen.append(url)
            return payload()

        latest_release(fetch)
        self.assertEqual(seen, [API_URL])

    def test_unreadable_tag_is_an_error_not_a_version(self) -> None:
        with self.assertRaisesRegex(UpdateError, "tag"):
            latest_release(lambda _url: payload("nightly"))

    def test_malformed_documents_are_errors(self) -> None:
        for body in (b"{not json", b"[]", b'{"tag_name": null}'):
            with self.subTest(body=body):
                with self.assertRaises(UpdateError):
                    latest_release(lambda _url, body=body: body)

    def test_network_errors_are_reported(self) -> None:
        def broken(_url: str) -> bytes:
            raise OSError("network is unreachable")

        with self.assertRaisesRegex(UpdateError, "could not reach GitHub"):
            latest_release(broken)

    def test_an_error_from_the_fetcher_is_kept(self) -> None:
        def rate_limited(_url: str) -> bytes:
            raise UpdateError("GitHub is limiting how often this can run")

        with self.assertRaisesRegex(UpdateError, "limiting"):
            latest_release(rate_limited)

    def test_a_release_without_a_page_falls_back_to_the_tag_url(self) -> None:
        release = latest_release(
            lambda _url: json.dumps({"tag_name": "v0.8.0"}).encode()
        )
        self.assertEqual(
            release.page,
            "https://github.com/EricBright/repopull/releases/tag/v0.8.0",
        )


class HelperTests(unittest.TestCase):
    def test_is_newer_is_false_when_the_running_version_is_unknown(self) -> None:
        release = Release(
            version=Version(0, 8, 0),
            tag="v0.8.0",
            page="",
            notes="",
            published="",
            asset=None,
            download=None,
        )
        self.assertFalse(is_newer(release, "unknown"))


if __name__ == "__main__":
    unittest.main()
