import os
import sys
import time
import json
import requests
import argparse
import lxml.html

from lxml.cssselect import CSSSelector

YOUTUBE_COMMENTS_URL = 'https://www.youtube.com/all_comments?v={youtube_id}'
YOUTUBE_COMMENTS_ORDER_URL = 'https://www.youtube.com/comment_ajax?action_load_comments=1&order_by_time={order_by_time}&filter={youtube_id}&order_menu=true'
YOUTUBE_COMMENTS_MORE_URL = 'https://www.youtube.com/comment_ajax?action_load_comments=1&order_by_time={order_by_time}&filter={youtube_id}'
YOUTUBE_REPLIES_URL = 'https://www.youtube.com/comment_ajax?action_load_replies=1&order_by_time={order_by_time}&filter={youtube_id}&tab=inbox'


def find_value(html, key, num_chars=2):
    pos_begin = html.find(key) + len(key) + num_chars
    pos_end = html.find('"', pos_begin)
    return html[pos_begin: pos_end]


def extract_comments(html):
    tree = lxml.html.fromstring(html)
    item_sel = CSSSelector('.comment-item')
    text_sel = CSSSelector('.comment-text-content')
    time_sel = CSSSelector('.time')

    for item in item_sel(tree):
        yield {'cid': item.get('data-cid'),
               'text': text_sel(item)[0].text_content(),
               'time': time_sel(item)[0].text_content().strip()}


def extract_reply_cids(html):
    tree = lxml.html.fromstring(html)
    sel = CSSSelector('.comment-replies-header > .load-comments')
    return [i.get('data-cid') for i in sel(tree)]


def download_comments(youtube_id, sleep=1, order_by_time=True):
    main_url = YOUTUBE_COMMENTS_URL.format(youtube_id=youtube_id)
    more_url = YOUTUBE_COMMENTS_MORE_URL.format(youtube_id=youtube_id, order_by_time=order_by_time)
    replies_url = YOUTUBE_REPLIES_URL.format(youtube_id=youtube_id, order_by_time=order_by_time)

    session = requests.Session()

    # Get Youtube page with initial comments
    response = session.get(main_url)
    html = response.text
    reply_cids = extract_reply_cids(html)

    ret_cids = []
    for comment in extract_comments(html):
        ret_cids.append(comment['cid'])
        yield comment

    page_token = find_value(html, 'data-token')
    session_token = find_value(html, 'XSRF_TOKEN', 4)

    first_iteration = True

    # Get remaining comments (the same as pressing the 'Show more' button)
    while page_token:
        data = {'video_id': youtube_id,
                'page_token': page_token,
                'session_token': session_token}

        if order_by_time and first_iteration:
            url = YOUTUBE_COMMENTS_ORDER_URL.format(youtube_id=youtube_id, order_by_time=True)
            data.pop('page_token')
        else:
            url = more_url
        response = session.post(url, data=data)

        first_iteration = False
        if response.status_code == 503:
            time.sleep(10)
            continue
        json_response = json.loads(response.text)

        html = json_response['html_content']
        reply_cids += extract_reply_cids(html)
        for comment in extract_comments(html):
            if comment['cid'] not in ret_cids:
                ret_cids.append(comment['cid'])
                yield comment

        page_token = json_response.get('page_token', None)
        time.sleep(sleep)

    # Get replies (the same as pressing the 'View all X replies' link)
    for cid in reply_cids:
        data = {'comment_id': cid,
                'video_id': youtube_id,
                'can_reply': 1,
                'session_token': session_token}

        response = session.post(replies_url, data=data)
        if response.status_code == 503:
            time.sleep(10)
            continue
        json_response = json.loads(response.text)

        html = json_response['html_content']
        for comment in extract_comments(html):
            if comment['cid'] not in ret_cids:
                ret_cids.append(comment['cid'])
                yield comment
        time.sleep(sleep)


def main(argv):
    parser = argparse.ArgumentParser(add_help=False, description=('Download Youtube comments without using the Youtube API'))
    parser.add_argument('--help', '-h', action='help', default=argparse.SUPPRESS, help='Show this help message and exit')
    parser.add_argument('--youtubeid', '-y', help='ID of Youtube video for which to download the comments')
    parser.add_argument('--output', '-o', help='Output filename (output format is line delimited JSON)')
    parser.add_argument('--time', '-t', action='store_true', help='Download Youtube comments ordered by time')

    try:
        args = parser.parse_args(argv)

        youtube_id = args.youtubeid
        output = args.output

        if not youtube_id or not output:
            parser.print_usage()
            raise ValueError('you need to specify a Youtube ID and an output filename')

        print 'Downloading Youtube comments for video:', youtube_id
        count = 0
        with open(output, 'wb') as fp:
            for comment in download_comments(youtube_id, order_by_time=bool(args.time)):
                print >> fp, json.dumps(comment)
                count += 1
                sys.stdout.write('Downloaded %d comment(s)\r' % count)
                sys.stdout.flush()
        print '\nDone!'


    except Exception, e:
        print 'Error:', str(e)
        sys.exit(1)


if __name__ == "__main__":
    main(sys.argv[1:])
