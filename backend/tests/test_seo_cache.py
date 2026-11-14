"""Offline cache/sitemap tests. No server imports, network or Mongo connections."""
import asyncio
import unittest
from collections import Counter
from types import SimpleNamespace
from unittest.mock import patch
from xml.etree import ElementTree as ET

from fastapi import HTTPException

from api import make_router
from api.async_cache import AsyncTTLValue
from api.pharmacies_seed import CITIES, PHARMACIES
from api.seo import CANONICAL_HOST, make_seo_router


class Clock:
    def __init__(self):
        self.now = 1000.0

    def __call__(self):
        return self.now


class Cursor:
    def __init__(self, rows, gate=None, error=None):
        self.rows = rows
        self.gate = gate
        self.error = error

    async def to_list(self, length):
        if self.gate is not None:
            await self.gate.wait()
        if self.error is not None:
            raise self.error
        return self.rows if length is None else self.rows[:length]

    def __aiter__(self):
        async def iterate():
            for row in await self.to_list(None):
                yield row
        return iterate()


class Prices:
    def __init__(self, rows):
        self.rows = rows
        self.calls = []
        self.gate = None
        self.error = None
        self.calls_changed = asyncio.Event()

    def aggregate(self, pipeline, **kwargs):
        self.calls.append((pipeline, kwargs))
        self.calls_changed.set()
        city = pipeline[0]["$match"].get("city")
        rows = [dict(row) for row in self.rows if not city or row["city"] == city]
        if pipeline[-1]["$project"] == {"_id": 0, "slug": "$_id.slug"}:
            rows = [{"slug": row["slug"]} for row in rows]
        else:
            rows.sort(key=lambda row: (row["city"], row["slug"]))
        return Cursor(rows, self.gate, self.error)

    async def wait_for_calls(self, count):
        while len(self.calls) < count:
            self.calls_changed.clear()
            await self.calls_changed.wait()


class Medications:
    def __init__(self, rows):
        self.rows = rows
        self.calls = []

    def aggregate(self, pipeline):
        self.calls.append(pipeline)
        allowed = pipeline[0]["$match"].get("slug", {}).get("$in")
        counts = Counter(
            row["category"] for row in self.rows
            if allowed is None or row["slug"] in allowed
        )
        return Cursor([{"_id": key, "count": value} for key, value in counts.items()])


def endpoint(router, path):
    return next(route.endpoint for route in router.routes if route.path == path)


def locations(response):
    root = ET.fromstring(response.body)
    return [node.text for node in root.findall("./*/{http://www.sitemaps.org/schemas/sitemap/0.9}loc")]


def seo_router_with_clock(db, clock):
    caches = []

    def make_cache(load, **options):
        cache = AsyncTTLValue(load, clock=clock, **options)
        caches.append(cache)
        return cache

    with patch("api.seo.AsyncTTLValue", side_effect=make_cache):
        router = make_seo_router(db)
    return router, caches[0]


class CacheTests(unittest.IsolatedAsyncioTestCase):
    async def test_concurrent_cold_readers_share_one_refresh_even_after_one_cancels(self):
        gate = asyncio.Event()
        started = asyncio.Event()
        calls = 0

        async def load():
            nonlocal calls
            calls += 1
            started.set()
            await gate.wait()
            return ["one snapshot"]

        cache = AsyncTTLValue(load, ttl=300, name="test")
        readers = [asyncio.create_task(cache.get()) for _ in range(20)]
        await started.wait()
        self.assertEqual(calls, 1)
        readers[0].cancel()
        with self.assertRaises(asyncio.CancelledError):
            await readers[0]
        gate.set()
        results = await asyncio.gather(*readers[1:])
        self.assertTrue(all(result is results[0] for result in results))
        self.assertEqual(calls, 1)

    async def test_ttl_starts_when_load_completes_and_refreshes_at_boundary(self):
        clock = Clock()
        calls = 0

        async def load():
            nonlocal calls
            calls += 1
            clock.now += 40  # An expensive query still gets a full TTL after completion.
            return calls

        cache = AsyncTTLValue(load, ttl=300, name="test", clock=clock)
        self.assertEqual(await cache.get(), 1)
        clock.now += 299
        self.assertEqual(await cache.get(), 1)
        clock.now += 1
        self.assertEqual(await cache.get(), 2)
        self.assertEqual(calls, 2)

    async def test_cold_failure_is_shared_and_can_retry_without_caching_empty_value(self):
        gate = asyncio.Event()
        started = asyncio.Event()
        calls = 0
        fail = True

        async def load():
            nonlocal calls
            calls += 1
            started.set()
            await gate.wait()
            if fail:
                raise RuntimeError("database unavailable")
            return ["recovered"]

        cache = AsyncTTLValue(load, ttl=300, stale_if_error=60, name="test")
        readers = [asyncio.create_task(cache.get()) for _ in range(10)]
        await started.wait()
        gate.set()
        results = await asyncio.gather(*readers, return_exceptions=True)
        self.assertEqual(calls, 1)
        self.assertTrue(all(isinstance(result, RuntimeError) for result in results))
        fail = False
        self.assertEqual(await cache.get(), ["recovered"])
        self.assertEqual(calls, 2)

    async def test_failure_stale_window_is_logged_and_never_extended(self):
        clock = Clock()
        fail = False

        async def load():
            if fail:
                raise RuntimeError("refresh failed")
            return ("last valid snapshot",)

        cache = AsyncTTLValue(load, ttl=300, stale_if_error=60, name="sitemap", clock=clock)
        valid = await cache.get()
        fail = True
        clock.now += 300
        with self.assertLogs("api.async_cache", level="WARNING") as logs:
            self.assertIs(await cache.get(), valid)
        self.assertIn("sitemap refresh failed", logs.output[0])
        clock.now += 59
        with self.assertLogs("api.async_cache", level="WARNING"):
            self.assertIs(await cache.get(), valid)
        clock.now += 1
        with self.assertRaisesRegex(RuntimeError, "refresh failed"):
            await cache.get()

    async def test_swr_returns_immediately_and_hard_expiry_waits_for_one_refresh(self):
        clock = Clock()
        gate = asyncio.Event()
        started = asyncio.Event()
        calls = 0

        async def load():
            nonlocal calls
            calls += 1
            if calls > 1:
                started.set()
                await gate.wait()
            return (calls,)

        cache = AsyncTTLValue(
            load, ttl=300, stale_if_error=60, stale_while_revalidate=True,
            name="sitemap", clock=clock,
        )
        original = await cache.get()
        clock.now += 300
        readers = await asyncio.wait_for(asyncio.gather(*(cache.get() for _ in range(20))), 1)
        self.assertTrue(all(value is original for value in readers))
        await started.wait()
        self.assertEqual(calls, 2)
        clock.now += 60
        hard_reader = asyncio.create_task(cache.get())
        await asyncio.sleep(0)
        self.assertFalse(hard_reader.done())
        self.assertEqual(calls, 2)
        gate.set()
        self.assertEqual(await hard_reader, (2,))
        clock.now += 299
        self.assertEqual(await cache.get(), (2,))
        self.assertEqual(calls, 2)

    async def test_swr_failure_backoff_bounds_retries_without_extending_stale_age(self):
        clock = Clock()
        fail = False
        calls = 0

        async def load():
            nonlocal calls
            calls += 1
            if fail:
                raise RuntimeError("refresh failed")
            return ("valid snapshot",)

        cache = AsyncTTLValue(
            load, ttl=300, stale_if_error=60, stale_while_revalidate=True,
            retry_delay=5, name="sitemap", clock=clock,
        )
        original = await cache.get()
        fail = True
        clock.now += 300
        with self.assertLogs("api.async_cache", level="WARNING"):
            self.assertIs(await cache.get(), original)
            await cache._inflight
        self.assertEqual(calls, 2)
        for _ in range(20):
            self.assertIs(await cache.get(), original)
        self.assertEqual(calls, 2)
        clock.now += 5
        with self.assertLogs("api.async_cache", level="WARNING"):
            self.assertIs(await cache.get(), original)
            await cache._inflight
        self.assertEqual(calls, 3)
        clock.now += 54
        with self.assertLogs("api.async_cache", level="WARNING"):
            self.assertIs(await cache.get(), original)
            await cache._inflight
        self.assertEqual(calls, 4)
        clock.now += 1  # Age=360; the last failure's 5-second backoff still applies.
        with self.assertRaisesRegex(RuntimeError, "refresh failed"):
            await cache.get()
        self.assertEqual(calls, 4)
        clock.now += 4
        with self.assertLogs("api.async_cache", level="WARNING"):
            with self.assertRaisesRegex(RuntimeError, "refresh failed"):
                await cache.get()
        self.assertEqual(calls, 5)

    async def test_loader_timeout_cleans_up_flight_and_allows_retry(self):
        gate = asyncio.Event()
        calls = 0

        async def load():
            nonlocal calls
            calls += 1
            await gate.wait()
            return ["recovered"]

        cache = AsyncTTLValue(load, ttl=300, load_timeout=0.01, name="test")
        results = await asyncio.gather(*(cache.get() for _ in range(10)), return_exceptions=True)
        self.assertTrue(all(isinstance(error, TimeoutError) for error in results))
        self.assertEqual(calls, 1)
        gate.set()
        self.assertEqual(await cache.get(), ["recovered"])
        self.assertEqual(calls, 2)


class SitemapTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.rows = [
            {"city": "msk", "slug": "alpha", "category": "ot-prostudy", "image_url": "/images/а б.png"},
            {"city": "msk", "slug": "beta", "category": "other", "image_url": "https://example.test/img?a=1&b=2"},
            {"city": "spb", "slug": "gamma", "category": "ot-prostudy", "image_url": None},
            {"city": "spb", "slug": "omega", "category": "obezbolivayuschie", "image_url": ""},
            {"city": "spb", "slug": "zeta", "category": None},
        ]
        self.prices = Prices(self.rows)
        self.db = SimpleNamespace(prices_real=self.prices)
        self.host = f"https://{CANONICAL_HOST}"

    async def test_parallel_xml_uses_one_snapshot_and_preserves_urls_images_and_chunk_404(self):
        gate = asyncio.Event()
        self.prices.gate = gate
        with patch("api.seo.SITEMAP_CHUNK_SIZE", 2):
            router = make_seo_router(self.db)
            index = endpoint(router, "/sitemap.xml")
            static = endpoint(router, "/sitemap_static.xml")
            categories = endpoint(router, "/sitemap_categories.xml")
            meds = endpoint(router, "/sitemap_meds_{idx}.xml")
            tasks = [asyncio.create_task(call) for call in (
                index(), static(), categories(), meds(1), meds(2), meds(3),
            )]
            # Let all readers enter the cache while Mongo's first query is blocked.
            await asyncio.wait_for(self.prices.wait_for_calls(1), 1)
            self.assertEqual(len(self.prices.calls), 1)
            gate.set()
            index_xml, static_xml, category_xml, *med_xmls = await asyncio.gather(*tasks)
            self.assertEqual(locations(index_xml), [
                f"{self.host}/sitemap_{part}.xml" for part in (
                    "static", "pharmacies", "categories", "meds_1", "meds_2", "meds_3",
                )
            ])
            expected_static = []
            for city in CITIES:
                paths = ["", "apteki"]
                if city["slug"] in {"msk", "spb"}:
                    paths.extend(["kategorii", "preparaty"])
                expected_static.extend(
                    f"{self.host}/{city['slug']}" + (f"/{path}" if path else "") for path in paths
                )
            expected_static.extend(f"{self.host}/{path}" for path in (
                "dlya-aptek", "o-servise", "kontakty", "politika-konfidencialnosti",
                "soglasie-na-obrabotku-pd",
            ))
            self.assertEqual(locations(static_xml), expected_static)
            self.assertEqual(locations(category_xml), [
                f"{self.host}/msk/kategorii/ot-prostudy",
                f"{self.host}/spb/kategorii/obezbolivayuschie",
                f"{self.host}/spb/kategorii/ot-prostudy",
            ])
            med_urls = [url for response in med_xmls for url in locations(response)]
            self.assertEqual(med_urls, [
                f"{self.host}/{row['city']}/preparaty/{row['slug']}" for row in self.rows
            ])
            self.assertEqual(len(set(med_urls)), len(self.rows))
            image_ns = "{http://www.google.com/schemas/sitemap-image/1.1}"
            images = ET.fromstring(med_xmls[0].body).findall(f".//{image_ns}loc")
            self.assertEqual([node.text for node in images], [
                f"{self.host}/images/%D0%B0%20%D0%B1.png", "https://example.test/img?a=1&b=2",
            ])
            for response in [static_xml, category_xml, *med_xmls]:
                self.assertNotIn(b"<lastmod>", response.body)
            # A source change cannot split count/categories/chunks within the TTL.
            self.prices.rows = []
            self.assertEqual((await meds(3)).body, med_xmls[2].body)
            self.assertEqual((await categories()).body, category_xml.body)
            for idx in (0, -1, 4):
                with self.assertRaises(HTTPException) as error:
                    await meds(idx)
                self.assertEqual(error.exception.status_code, 404)
            pharmacies_xml = await endpoint(router, "/sitemap_pharmacies.xml")()
            self.assertEqual(locations(pharmacies_xml), [
                f"{self.host}/{row['city']}/apteki/{row['id']}" for row in PHARMACIES
            ])
            self.assertEqual(len(self.prices.calls), 1)
            pipeline, options = self.prices.calls[0]
            self.assertTrue(options["allowDiskUse"])
            self.assertEqual(options["maxTimeMS"], 60000)
            self.assertEqual(pipeline[-2], {"$sort": {"_id.city": 1, "_id.slug": 1}})
            self.assertEqual(set(pipeline[-1]["$project"]), {"_id", "city", "slug", "category", "image_url"})
            self.assertEqual(pipeline[0]["$match"]["price"], {"$gt": 0})
            self.assertEqual(pipeline[-3], {"$match": {"$expr": {"$gte": [{"$size": "$nets"}, 2]}}})

    async def test_snapshot_refresh_failure_does_not_turn_sitemap_into_an_empty_success(self):
        clock = Clock()
        router, cache = seo_router_with_clock(self.db, clock)
        index = endpoint(router, "/sitemap.xml")
        valid_xml = await index()
        clock.now += 300
        self.prices.error = RuntimeError("Mongo down")
        with self.assertLogs("api.async_cache", level="WARNING"):
            self.assertEqual((await index()).body, valid_xml.body)
            await cache._inflight
        clock.now += 60
        with self.assertLogs("api.async_cache", level="WARNING"):
            with self.assertRaisesRegex(RuntimeError, "Mongo down"):
                await index()
        self.prices.error = None
        self.prices.rows = []  # An actual successful empty query is valid.
        clock.now += 5  # The bounded retry delay applies to hard-expired failures too.
        refreshed = await index()
        self.assertEqual(len(locations(refreshed)), 3)
        self.assertEqual(len(self.prices.calls), 4)

    async def test_cold_sitemap_database_error_propagates(self):
        clock = Clock()
        self.prices.error = RuntimeError("Mongo down")
        router, _ = seo_router_with_clock(self.db, clock)
        index = endpoint(router, "/sitemap.xml")
        with self.assertLogs("api.async_cache", level="WARNING"):
            with self.assertRaisesRegex(RuntimeError, "Mongo down"):
                await index()
        for _ in range(10):
            with self.assertRaisesRegex(RuntimeError, "Mongo down"):
                await index()
        self.assertEqual(len(self.prices.calls), 1)
        clock.now += 5
        with self.assertLogs("api.async_cache", level="WARNING"):
            with self.assertRaisesRegex(RuntimeError, "Mongo down"):
                await index()
        self.assertEqual(len(self.prices.calls), 2)

    async def test_all_sitemap_readers_share_one_immediate_swr_snapshot_and_hard_limit(self):
        clock = Clock()
        with patch("api.seo.SITEMAP_CHUNK_SIZE", 2):
            router, _ = seo_router_with_clock(self.db, clock)
            index = endpoint(router, "/sitemap.xml")
            static = endpoint(router, "/sitemap_static.xml")
            categories = endpoint(router, "/sitemap_categories.xml")
            meds = endpoint(router, "/sitemap_meds_{idx}.xml")

            async def all_xml():
                return await asyncio.gather(index(), static(), categories(), meds(1), meds(2), meds(3))

            original = await all_xml()
            self.assertEqual(len(self.prices.calls), 1)
            gate = asyncio.Event()
            self.prices.gate = gate
            self.prices.rows = self.rows[2:3]
            clock.now += 300
            # The refresh is blocked in fake Mongo; every XML must still return immediately.
            readers = await asyncio.wait_for(asyncio.gather(*(all_xml() for _ in range(10))), 1)
            for group in readers:
                self.assertEqual([response.body for response in group], [response.body for response in original])
            await asyncio.wait_for(self.prices.wait_for_calls(2), 1)
            self.assertEqual(len(self.prices.calls), 2)
            clock.now += 60
            hard_reader = asyncio.create_task(index())
            await asyncio.sleep(0)
            self.assertFalse(hard_reader.done())
            gate.set()
            refreshed_index = await hard_reader
            self.assertEqual(locations(refreshed_index)[3:], [f"{self.host}/sitemap_meds_1.xml"])
            self.assertEqual(locations(await meds(1)), [f"{self.host}/spb/preparaty/gamma"])
            self.assertEqual(locations(await categories()), [f"{self.host}/spb/kategorii/ot-prostudy"])
            self.assertNotIn(f"{self.host}/msk/preparaty", locations(await static()))
            self.assertEqual(len(self.prices.calls), 2)

    async def test_city_slug_cache_deduplicates_per_city_refresh_and_does_not_serve_stale(self):
        clock = Clock()
        self.db.medications = Medications(self.rows)
        with patch("api.async_cache.monotonic", clock):
            router = make_router(self.db)
            categories = endpoint(router, "/categories")
            gate = asyncio.Event()
            self.prices.gate = gate
            tasks = [asyncio.create_task(categories(city=city)) for city in ("msk",) * 8 + ("spb",) * 4]
            await asyncio.wait_for(self.prices.wait_for_calls(2), 1)
            self.assertEqual(len(self.prices.calls), 2)
            self.assertTrue(all(options["maxTimeMS"] == 60000 for _, options in self.prices.calls))
            gate.set()
            results = await asyncio.gather(*tasks)
            msk_counts = {row["slug"]: row["count"] for row in results[0]}
            spb_counts = {row["slug"]: row["count"] for row in results[-1]}
            self.assertEqual(msk_counts["ot-prostudy"], 1)
            self.assertEqual(spb_counts["obezbolivayuschie"], 1)
            clock.now += 299
            await categories(city="msk")
            self.assertEqual(len(self.prices.calls), 2)
            clock.now += 1
            self.prices.rows = [row for row in self.rows if row["slug"] != "alpha"]
            refreshed = await categories(city="msk")
            self.assertEqual(next(row["count"] for row in refreshed if row["slug"] == "ot-prostudy"), 0)
            self.assertEqual(len(self.prices.calls), 3)
            clock.now += 300
            self.prices.error = RuntimeError("Mongo down")
            with self.assertRaisesRegex(RuntimeError, "Mongo down"):
                await categories(city="msk")


if __name__ == "__main__":
    unittest.main()
