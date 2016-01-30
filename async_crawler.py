#!/usr/bin/env python

# python dictionary object to html5 json form generator.
# https://github.com/mehmetkose/python3-async-crawler

# Licensed under the MIT license:
# http://www.opensource.org/licenses/mit-license
# Copyright (c) 2016 Mehmet Kose mehmet@linux.com


import aiohttp
import asyncio
from urllib.parse import urljoin, urldefrag

root_url = "http://python.org"
crawled_urls = []
url_hub = [root_url, "%s/robots.txt" % (root_url), "%s/sitemap.xml" % (root_url)]

async def get_body(client, url):
    async with client.get(url) as response:
        return await response.read()

def remove_fragment(url):
    pure_url, frag = urldefrag(url)
    return pure_url

def get_links(html):
    new_urls = [link.split('"')[0] for link in str(html).replace("'",'"').split('href="')[1:]]
    return [urljoin(root_url, remove_fragment(new_url)) for new_url in new_urls]

if __name__ == '__main__':
    loop = asyncio.get_event_loop()
    client = aiohttp.ClientSession(loop=loop)
    for to_crawl in url_hub:
        raw_html = loop.run_until_complete(get_body(client, to_crawl))
        for link in get_links(raw_html):
            if root_url in link and not link in crawled_urls:
                url_hub.append(link)
        url_hub.remove(to_crawl)
        crawled_urls.append(to_crawl)
        print("url hub: %s | crawled: %s  |url : %s" % (len(url_hub), len(crawled_urls), to_crawl))
    client.close()

