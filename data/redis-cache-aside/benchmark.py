"""
Hits /products/{id} a bunch of times and prints the latency for the first
(cold, cache miss) call vs the following ones (warm, cache hit). Also prints
the returned `price` for each call — fetch_product() randomizes price on
every real execution, so identical prices across calls is itself proof the
handler didn't actually re-run, not just that the response was fast.
"""
import sys
import time

import httpx

BASE_URL = "http://localhost:8000"
PRODUCT_ID = 42
REPEATS = 5


def main():
    print(f"GET /products/{PRODUCT_ID} x{REPEATS}\n")
    prices = []
    prev_misses = httpx.get(f"{BASE_URL}/cache-stats", timeout=10).json()["misses"]
    for i in range(REPEATS):
        start = time.perf_counter()
        resp = httpx.get(f"{BASE_URL}/products/{PRODUCT_ID}", timeout=10)
        elapsed_ms = (time.perf_counter() - start) * 1000
        resp.raise_for_status()
        data = resp.json()
        prices.append(data["price"])

        # label by what actually happened server-side, not by "call 1 must be
        # cold" - a previous benchmark run within the same TTL window would
        # make that assumption wrong
        misses_now = httpx.get(f"{BASE_URL}/cache-stats", timeout=10).json()["misses"]
        label = "COLD (cache miss)" if misses_now > prev_misses else "WARM (cache hit)"
        prev_misses = misses_now
        print(f"  call {i + 1}: {elapsed_ms:7.1f} ms   price={data['price']:<8} {label}")

    if len(set(prices)) == 1:
        print("\nOK: price was identical on every call, including the first -> "
              "once cached, the handler body never re-ran.")
    else:
        print("\nWARNING: prices differed across calls, check the cache is actually wired up.")

    stats = httpx.get(f"{BASE_URL}/cache-stats", timeout=10).json()
    print(f"\ncache stats: {stats}")


if __name__ == "__main__":
    try:
        main()
    except httpx.ConnectError:
        print("could not reach the app - is it running on :8000?", file=sys.stderr)
        sys.exit(1)
