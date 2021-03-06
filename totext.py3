#!/usr/bin/env python2
# Author: Remy van Elst <raymii.org>
# License: GNU GPLv2

# pip install html2text requests readability-lxml feedparser lxml
import requests
import lxml
from readability import Document
import html2text
import argparse 
import feedparser
import sys
import time
import re
import os
from datetime import datetime
from time import mktime
from urllib.parse import urlparse
import urllib3
#The only insecure call we do is on purpose.
urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)
import warnings
warnings.simplefilter(action='ignore', category=FutureWarning)

parser = argparse.ArgumentParser(description='Convert HTML page to text using readability and html2text.')
parser.add_argument('-u','--url', help='URL to convert', required=True)
parser.add_argument('-s','--sleep', help='Sleep X seconds between URLs (only in rss)', default=3)
parser.add_argument('-t','--timeout', help='Timeout for HTTP requests', default=30)
parser.add_argument('-r', '--rss', help="URL is RSS feed. Parse every item in feed", 
    default=False, action="store_true")
parser.add_argument('-n', '--noprint', help="Dont print converted contents", 
    default=False, action="store_true")
parser.add_argument('-o', '--original', help="Dont parse contents with readability.", 
    default=False, action="store_true")
parser.add_argument('-f', '--forcedownload', 
    help="Force download even if file seems to be something else than text based on the content-type header.", 
    default=False, action="store_true")
args = vars(parser.parse_args())

class mockResponse(object):
    text = ""
    def __init__(self, text):
        super(mockResponse, self).__init__()
        self.text = text
        
def cookie_workaround_ad(url):
    hostname = urlparse(url).hostname
    if hostname == "ad.nl" or hostname == "www.ad.nl":
        url = "https://www.ad.nl/accept?url=" + url
    return url

def custom_workaround_twitter(url):
    hostname = urlparse(url).hostname
    if hostname == "twitter.com" or hostname == "www.twitter.com":
        session_requests = requests.session()
        path = urlparse(url).path
        jar = requests.cookies.RequestsCookieJar()
        content = session_requests.get(url, headers=headers, 
            timeout=args['timeout'], cookies=jar)
        content.encoding = content.apparent_encoding
        tree = lxml.html.fromstring(content.text)
        auth_token = list(set(
            tree.xpath("//input[@name='authenticity_token']/@value")))[0]
        url = "https://mobile.twitter.com/" + path
        payload = {"authenticity_token": auth_token}
        content2 = session_requests.get(url, headers=headers, 
            timeout=args['timeout'], cookies=jar, allow_redirects=True)
        content2.encoding = content2.apparent_encoding
        content2.raise_for_status()
        args['original'] = True
        return content2
       
def custom_workaround_noparse(url):
    hostname = urlparse(url).hostname
    if hostname == "news.ycombinator.com" or \
    hostname == "youtube.com" or \
    hostname == "www.youtube.com":
        args['original'] = True

def cookie_workaround_tweakers(url):
    hostname = urlparse(url).hostname
    if hostname == "tweakers.net" or hostname == "www.tweakers.net":
        headers['X-Cookies-Accepted'] = '1'

def custom_workaround_verisimilitudes(url):
    hostname = urlparse(url).hostname
    if hostname == "verisimilitudes.net" or hostname == "www.verisimilitudes.net":
        path = urlparse(url).path.replace("/","",1)
        if(path):
            response = get_url(args['url'], workarounds=False)
            doc = convert_doc(response.text)
            text = str(convert_doc_to_text(doc.content()))
            if not text:
                title = "Parsing failed"
            else:
                title = doc.short_title().strip()
            save_gophermap("", title, hostname, 1, path, 70)

def cookie_workaround_rd(url):
    hostname = urlparse(url).hostname
    if hostname == "rd.nl" or hostname == "www.rd.nl":
        headers['cookieInfoV4'] = "1"

def cookie_workaround_geenstijl(url):
    hostname = urlparse(url).hostname
    if hostname == "geenstijl.nl" or hostname == "www.geenstijl.nl":
        headers['Cookie'] = "cpc=10"

def cookie_workarounds_url(url):
    url = cookie_workaround_ad(url)
    return url

def cookie_workarounds_header(url):
    cookie_workaround_tweakers(url)
    cookie_workaround_rd(url)
    cookie_workaround_geenstijl(url)

def custom_content_workaround(url):
    custom_content = custom_workaround_twitter(url)
    custom_workaround_noparse(url)
    custom_workaround_verisimilitudes(url)
    return custom_content

def get_url(url, workarounds=True):
    if workarounds:
        url = cookie_workarounds_url(url)
        cookie_workarounds_header(url)
        custom_content = custom_content_workaround(url)
        if custom_content:
            return custom_content
    try:
        r = requests.get(url, headers=headers, 
            timeout=args['timeout'])
        r.raise_for_status()
    except requests.exceptions.SSLError as e:
        print("SSL Error. Retrying once")
        time.sleep(5)
        r = requests.get(url, headers=headers, 
            timeout=args['timeout'], verify=False)
        r.raise_for_status()
    except requests.exceptions.HTTPError as e:
        print("HTTP Error. Retrying once")
        time.sleep(5)
        r = requests.get(url, headers=headers, 
            timeout=args['timeout'])
    except requests.exceptions.ReadTimeout as e:
        print("ReadTimeout, retrying once")
        time.sleep(5)
        r = requests.get(url, headers=headers, 
            timeout=args['timeout'])
        r.raise_for_status()
    
    r.encoding = r.apparent_encoding
    try:
        if "message" in r.headers['content-type'] or \
           "image" in r.headers['content-type'] or \
           "pdf" in r.headers['content-type'] or \
           "model" in r.headers['content-type'] or \
           "multipart" in r.headers['content-type'] or \
           "audio" in r.headers['content-type'] or \
           "font" in r.headers['content-type'] or \
           "video" in r.headers['content-type']:
            if args['forcedownload']:
                return r
            else:
                return mockResponse("""This might not be a html file but something 
                else, like a PDF or an audio file. Use the --forcedownload flag
                to download and parse this anyway. The content type reported for 
                this file is: %s\n\n""" % (r.headers['content-type']))
    except KeyError:
        pass
    if len(r.text) > 5:
        return r 
    else:
        return mockResponse("Empty Response")


def convert_doc(html_text):
    return Document(input=html_text, 
        positive_keywords=["articleColumn", "article", "content", 
        "category_news"],
        negative_keywords=["commentColumn", "comment", "comments", 
        "posting_list reply", "posting reply", "reply"])


def convert_doc_to_text(doc_summary):
    h = html2text.HTML2Text()
    h.inline_links = False # reference style links
    h.wrap_links = False 
    h.body_width = 72
    doc = h.handle(doc_summary).strip()
    if len(doc) > 500:
        return doc
    
def save_doc(text, title, url, rssDate=0):
    hostname = urlparse(url).hostname
    if not os.path.exists("saved/" + hostname):
        os.makedirs("saved/" + hostname)
    filename = re.sub(r'[^A-Za-z0-9]', '_', title)
    if rssDate:
        posttime = datetime.fromtimestamp(mktime(rssDate)).strftime("%Y%m%dT%H%M")
    else:
        posttime = datetime.now().strftime("%Y%m%dT%H%M")
    filename = "saved/" + hostname + "/" + posttime + "_" + filename + ".txt"
    if not os.path.exists(filename):
        with open(filename, "w") as textfile:
            textfile.write("# " + title)
            textfile.write("\nSource URL: \t" + url)
            textfile.write("\nDate: \t\t" + posttime)
            textfile.write("\n\n")
            textfile.write(text)  
    return filename

def save_gophermap(text, title, server, gophertype, filename, gopherport):
    if not os.path.exists("saved/" + server):
        os.makedirs("saved/" + server)
    posttime = datetime.now().strftime("%Y%m%dT%H%M")
    if not os.path.exists("saved/" + server + "/" + posttime):
        os.makedirs("saved/" + server + "/" + posttime)
    gmfile = "saved/" + server + "/" + posttime + "/gophermap"
    if not os.path.exists(gmfile):
        with open(gmfile, "w") as gophermap:
            gophermap.write("i\t/\tlocalhost\t70\n")
            gophermap.write("iThis article is available via Gopher. \t/\tlocalhost\t70\n")
            gophermap.write("iPlease follow the link\t/\tlocalhost\t70\n")
            gophermap.write(("%i%s on %s\t/%s\t%s\t%i\n") % (gophertype, 
                title, server, filename, server, gopherport))
            gophermap.write("i\t/\tlocalhost\t70\n")
            gophermap.write(("iLast update: %s\t/\tlocalhost\t70\n") % (posttime))
            gophermap.write(text)
    return gmfile

headers = {'User-Agent': 'Tiny Tiny RSS/19.2 (1a484ec) (http://tt-rss.org/)'} 

response = get_url(args['url'])

if args['rss']:
    feed = feedparser.parse(response.text)
    if feed.bozo:
        print("Invalid XML.")
        sys.exit(1)
    else:
        for post in feed.entries:
            try:
                response = get_url(post['link'])
            except Exception as e:
                response = mockResponse("Failed to get RSS article.")
            doc = convert_doc(response.text)
            if args['original']:
                text = str(convert_doc_to_text(doc.content()))
            else:
                text = convert_doc_to_text(doc.summary())
                if not text:
                    text = "Parsing with Readability failed. Original content:\n\n"
                    text += str(convert_doc_to_text(doc.content()))
            title = doc.short_title().strip()
            try:
                rssDate = post['published_parsed']
            except KeyError:
                try:
                    rssDate = post['updated_parsed']
                except KeyError:
                    rssDate = post['created_parsed']
            filename = save_doc(text, title[:150], post['link'], rssDate)
            if not args['noprint']:
                print("\n\n========================\n\n") 
                print(("# " + title))
                print(("Source URL: " + post['link']))
                print("\n")
                print(text)
                print(("file saved as " + filename))
            if args['sleep']:
                time.sleep(args['sleep'])
else:
    doc = convert_doc(response.text)
    if args['original']:
        text = str(convert_doc_to_text(doc.content()))
    else:
        text = convert_doc_to_text(doc.summary())
        if not text:
            text = "Parsing with Readability failed. Original content:\n\n"
            text += str(convert_doc_to_text(doc.content()))
    title = doc.short_title().strip()
    filename = save_doc(text, title[:150], args['url'])
    if not args['noprint']:
        print("\n\n========================\n\n") 
        print(("# " + title))
        print(("Source URL: " + args['url']))
        print("\n")
        print(text)
        print(("file saved as " + filename))
