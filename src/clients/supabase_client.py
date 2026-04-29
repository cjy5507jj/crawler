"""Singleton Supabase client.

httpx default(http2=True) keep-alive 가 launchd 환경에서 vocab/discovery
단계에서 `httpx.RemoteProtocolError: ConnectionTerminated` 로 끊기는 사례가
4/26~28 두 번 발생했음. 원인은 HTTP/2 multiplexing 의 idle stream 정리
시점이 Supabase edge proxy 와 어긋나는 것. supabase-py v2.29 부터
`SyncClientOptions.httpx_client` 로 underlying httpx Client 를 주입할 수
있어, 본 모듈에서 HTTP/1.1 강제 + retries=2 transport 를 명시적으로 구성한다.
"""

from __future__ import annotations

import os
from functools import lru_cache

import httpx
from dotenv import load_dotenv
from supabase import Client, create_client
from supabase.lib.client_options import SyncClientOptions

load_dotenv()


def _build_httpx_client() -> httpx.Client:
    """HTTP/1.1 + 짧은 keep-alive + 재시도. PostgREST/REST 모두 공유."""
    return httpx.Client(
        http2=False,
        timeout=httpx.Timeout(connect=10.0, read=30.0, write=30.0, pool=5.0),
        limits=httpx.Limits(
            max_keepalive_connections=4,
            max_connections=8,
            keepalive_expiry=20.0,
        ),
        transport=httpx.HTTPTransport(retries=2),
        follow_redirects=True,
    )


@lru_cache(maxsize=1)
def get_client() -> Client:
    url = os.environ["SUPABASE_URL"]
    key = os.environ["SUPABASE_KEY"]
    options = SyncClientOptions(httpx_client=_build_httpx_client())
    return create_client(url, key, options=options)
