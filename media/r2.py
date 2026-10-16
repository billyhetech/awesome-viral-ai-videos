"""Minimal S3-compatible uploader for Cloudflare R2 (stdlib only, AWS SigV4).

Env (same names as the ClawShelf app, so values can be copied from Vercel):
  STORAGE_ENDPOINT          https://<account_id>.r2.cloudflarestorage.com
  STORAGE_BUCKET_NAME       bucket name
  STORAGE_ACCESS_KEY_ID / STORAGE_SECRET_ACCESS_KEY
  STORAGE_REGION            "auto" for R2 (default)
  STORAGE_PUBLIC_URL        public base URL of the bucket, e.g. https://media.clawshelf.com
"""
import hashlib
import hmac
import os
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timezone


def _hmac(key, msg):
    return hmac.new(key, msg.encode("utf-8"), hashlib.sha256).digest()


def signing_key(secret_key, date_stamp, region, service="s3"):
    k = _hmac(("AWS4" + secret_key).encode("utf-8"), date_stamp)
    k = _hmac(k, region)
    k = _hmac(k, service)
    return _hmac(k, "aws4_request")


def sign(method, host, path, headers, payload_hash, access_key, secret_key, region, query=""):
    """Return the Authorization header for an S3 request (SigV4, header auth).

    `headers` must already contain host, x-amz-date and x-amz-content-sha256;
    every header passed in is signed.
    """
    amz_date = headers["x-amz-date"]
    date_stamp = amz_date[:8]
    canon_headers = {k.lower().strip(): " ".join(str(v).split()) for k, v in headers.items()}
    signed = ";".join(sorted(canon_headers))
    canonical_request = "\n".join([
        method,
        urllib.parse.quote(path, safe="/~"),
        query,
        "".join(f"{k}:{canon_headers[k]}\n" for k in sorted(canon_headers)),
        signed,
        payload_hash,
    ])
    scope = f"{date_stamp}/{region}/s3/aws4_request"
    string_to_sign = "\n".join([
        "AWS4-HMAC-SHA256", amz_date, scope,
        hashlib.sha256(canonical_request.encode("utf-8")).hexdigest(),
    ])
    signature = hmac.new(signing_key(secret_key, date_stamp, region),
                         string_to_sign.encode("utf-8"), hashlib.sha256).hexdigest()
    return (f"AWS4-HMAC-SHA256 Credential={access_key}/{scope}, "
            f"SignedHeaders={signed}, Signature={signature}")


class R2:
    def __init__(self, endpoint, bucket, access_key, secret_key, public_url, region="auto"):
        self.endpoint = endpoint.rstrip("/")
        self.bucket = bucket
        self.access_key = access_key
        self.secret_key = secret_key
        self.public_url = public_url.rstrip("/")
        self.region = region or "auto"

    @classmethod
    def from_env(cls):
        need = ["STORAGE_ENDPOINT", "STORAGE_BUCKET_NAME", "STORAGE_ACCESS_KEY_ID",
                "STORAGE_SECRET_ACCESS_KEY", "STORAGE_PUBLIC_URL"]
        missing = [k for k in need if not os.environ.get(k, "").strip()]
        if missing:
            return None, f"R2 not configured (missing {', '.join(missing)})"
        return cls(
            os.environ["STORAGE_ENDPOINT"].strip(),
            os.environ["STORAGE_BUCKET_NAME"].strip(),
            os.environ["STORAGE_ACCESS_KEY_ID"].strip(),
            os.environ["STORAGE_SECRET_ACCESS_KEY"].strip(),
            os.environ["STORAGE_PUBLIC_URL"].strip(),
            os.environ.get("STORAGE_REGION", "auto").strip(),
        ), None

    def public(self, key):
        return f"{self.public_url}/{urllib.parse.quote(key, safe='/~')}"

    def put_file(self, key, file_path, content_type, sha256_hex, size):
        """Upload a local file; returns its public URL."""
        host = urllib.parse.urlparse(self.endpoint).netloc
        path = f"/{self.bucket}/{key}"
        headers = {
            "host": host,
            "x-amz-date": datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ"),
            "x-amz-content-sha256": sha256_hex,
            "content-type": content_type,
            "cache-control": "public, max-age=31536000, immutable",
        }
        auth = sign("PUT", host, path, headers, sha256_hex,
                    self.access_key, self.secret_key, self.region)
        url = f"{self.endpoint}{urllib.parse.quote(path, safe='/~')}"
        with open(file_path, "rb") as body:
            req = urllib.request.Request(url, data=body, method="PUT", headers={
                **{k: v for k, v in headers.items() if k != "host"},
                "Authorization": auth,
                "Content-Length": str(size),
            })
            try:
                with urllib.request.urlopen(req, timeout=600) as r:
                    r.read()
            except urllib.error.HTTPError as e:
                raise RuntimeError(f"R2 PUT {key} failed: {e.code} {e.read()[:300]!r}") from e
        return self.public(key)
