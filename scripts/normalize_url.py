"""URL normalizer for Polygraph runner."""


def normalize_base_url(url: str | None) -> str | None:
    """Canonicalize URLs by removing trailing slashes, default ports, and whitespace.

    Args:
        url: URL to normalize, or None/empty string

    Returns:
        Normalized URL, or the original input if None/empty
    """
    # Handle None and empty cases explicitly
    if url is None or url == "":
        return url
    
    # Strip leading/trailing whitespace
    url = url.strip()
    
    # If now empty after stripping, return as-is (empty string)
    if url == "":
        return ""
    
    from urllib.parse import urlparse
    
    parsed = urlparse(url)
    
    # Normalize scheme to lowercase
    scheme = parsed.scheme.lower()
    
    # Normalize the netloc (lowercase)
    netloc = parsed.netloc.lower()
    
    # Remove default ports
    if parsed.port is not None:
        if (parsed.scheme == "http" and parsed.port == 80) or \
           (parsed.scheme == "https" and parsed.port == 443):
            netloc = netloc.split(":")[0]
    
    # Remove trailing dot from domain (if present)
    if netloc.endswith("."):
        netloc = netloc[:-1]
    
    # For path - remove trailing slash unless it's root
    # Only strip trailing / from path if it exists and is not the only character
    if parsed.path != "/":
        path = parsed.path.rstrip("/")
    else:
        path = "/"
    
    # Reconstruct URL
    return scheme + "://" + netloc + path
