"""Block explorers. Any Esplora API works: your own (electrs, or mempool on an Umbrel) or public."""

from urllib.parse import urlparse

PUBLIC = {
    "bitcoin": ["https://mempool.space/api", "https://blockstream.info/api"],
    "signet": ["https://mempool.space/signet/api", "https://blockstream.info/signet/api"],
    "testnet4": ["https://mempool.space/testnet4/api", "https://blockstream.info/testnet4/api"],
}


def explorer_urls(network: str, configured: str = "") -> list[str]:
    """The comma-separated list given, in order, or the public explorers for the network."""
    urls = [url.strip().rstrip("/") for url in configured.split(",") if url.strip()]
    for url in urls:
        parsed = urlparse(url)
        if parsed.scheme not in ("http", "https") or not parsed.netloc:
            raise ValueError(f"Not a block explorer address: {url}")
    return urls or list(PUBLIC[network])
