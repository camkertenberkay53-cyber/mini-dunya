"""YouTube Data API v3 ile yükleme (yenileme jetonu ile, ek kütüphane gerektirmez)."""
import json
import os
import urllib.parse
import urllib.request
import urllib.error


class YTError(Exception):
    pass


def configured(token_env='YT_REFRESH_TOKEN'):
    return all(os.environ.get(k) for k in ('YT_CLIENT_ID', 'YT_CLIENT_SECRET', token_env))


def access_token(token_env='YT_REFRESH_TOKEN'):
    data = urllib.parse.urlencode({
        'client_id': os.environ['YT_CLIENT_ID'], 'client_secret': os.environ['YT_CLIENT_SECRET'],
        'refresh_token': os.environ[token_env], 'grant_type': 'refresh_token'}).encode()
    try:
        with urllib.request.urlopen(urllib.request.Request('https://oauth2.googleapis.com/token', data=data), timeout=30) as r:
            return json.loads(r.read())['access_token']
    except urllib.error.HTTPError as e:
        raise YTError(f'YouTube yetkilendirme hatası: {e.code} {e.read()[:300]!r}')


def upload(video_path, title, description, tags, privacy='public', category=23, thumb=None, log=print,
           token_env='YT_REFRESH_TOKEN', lang='tr', publish_at=None):
    tok = access_token(token_env)
    meta = {
        'snippet': {'title': title[:100], 'description': description[:4900], 'tags': tags[:30],
                    'categoryId': str(category), 'defaultLanguage': lang, 'defaultAudioLanguage': lang},
        'status': ({'privacyStatus': 'private', 'publishAt': publish_at} if publish_at else {'privacyStatus': privacy})
                  | {'selfDeclaredMadeForKids': False, 'embeddable': True},
    }
    size = os.path.getsize(video_path)
    req = urllib.request.Request(
        'https://www.googleapis.com/upload/youtube/v3/videos?uploadType=resumable&part=snippet,status',
        data=json.dumps(meta).encode(), method='POST',
        headers={'Authorization': f'Bearer {tok}', 'Content-Type': 'application/json; charset=UTF-8',
                 'X-Upload-Content-Type': 'video/mp4', 'X-Upload-Content-Length': str(size)})
    try:
        with urllib.request.urlopen(req, timeout=60) as r:
            loc = r.headers['Location']
    except urllib.error.HTTPError as e:
        raise YTError(f'Yükleme başlatılamadı: {e.code} {e.read()[:500]!r}')
    with open(video_path, 'rb') as fh:
        body = fh.read()
    req = urllib.request.Request(loc, data=body, method='PUT',
                                 headers={'Authorization': f'Bearer {tok}', 'Content-Type': 'video/mp4', 'Content-Length': str(size)})
    try:
        with urllib.request.urlopen(req, timeout=1800) as r:
            vid = json.loads(r.read())['id']
    except urllib.error.HTTPError as e:
        raise YTError(f'Yükleme başarısız: {e.code} {e.read()[:500]!r}')
    log(f'YouTube: https://youtu.be/{vid} ({privacy})')
    if thumb and os.path.exists(thumb):
        try:
            with open(thumb, 'rb') as fh:
                img = fh.read()
            r = urllib.request.Request(f'https://www.googleapis.com/upload/youtube/v3/thumbnails/set?videoId={vid}',
                                       data=img, method='POST', headers={'Authorization': f'Bearer {tok}', 'Content-Type': 'image/jpeg'})
            urllib.request.urlopen(r, timeout=60).read()
        except Exception as e:  # kapak için telefon doğrulaması gerekebilir; video yine de yayında
            log(f'  Kapak görseli yüklenemedi (önemli değil): {e}')
    return vid


def stats(ids, token_env='YT_REFRESH_TOKEN', full=False):
    if not ids:
        return {}
    tok = access_token(token_env)
    url = 'https://www.googleapis.com/youtube/v3/videos?part=statistics&id=' + ','.join(ids[:50])
    with urllib.request.urlopen(urllib.request.Request(url, headers={'Authorization': f'Bearer {tok}'}), timeout=30) as r:
        data = json.loads(r.read())
    if full:
        return {it['id']: {k: int(v) for k, v in it['statistics'].items() if str(v).isdigit()} for it in data.get('items', [])}
    return {it['id']: int(it['statistics'].get('viewCount', 0)) for it in data.get('items', [])}


# ---------------------------------------------------------------- kanal yönetimi (youtube.force-ssl / yt-analytics yetkisi gerekir)
_TOK = {}


def _tok(token_env):
    if token_env not in _TOK:
        _TOK[token_env] = access_token(token_env)
    return _TOK[token_env]


def _api(method, url, token_env, body=None):
    data = json.dumps(body).encode() if body is not None else None
    req = urllib.request.Request(url, data=data, method=method,
                                 headers={'Authorization': f'Bearer {_tok(token_env)}', 'Content-Type': 'application/json'})
    try:
        with urllib.request.urlopen(req, timeout=60) as r:
            raw = r.read()
            return json.loads(raw) if raw else {}
    except urllib.error.HTTPError as e:
        raise YTError(f'{e.code} {e.read()[:300]!r}')


def playlist_ensure(title, description, token_env='YT_REFRESH_TOKEN', lang='tr'):
    """Bu başlıkta bir oynatma listesi varsa id'sini döndürür, yoksa herkese açık olarak oluşturur."""
    page = ''
    for _ in range(5):
        d = _api('GET', 'https://www.googleapis.com/youtube/v3/playlists?part=snippet&mine=true&maxResults=50' + (f'&pageToken={page}' if page else ''), token_env)
        for it in d.get('items', []):
            if it['snippet']['title'] == title:
                return it['id']
        page = d.get('nextPageToken')
        if not page:
            break
    d = _api('POST', 'https://www.googleapis.com/youtube/v3/playlists?part=snippet,status', token_env,
             {'snippet': {'title': title, 'description': description, 'defaultLanguage': lang},
              'status': {'privacyStatus': 'public'}})
    return d['id']


def playlist_add(playlist_id, video_id, token_env='YT_REFRESH_TOKEN'):
    _api('POST', 'https://www.googleapis.com/youtube/v3/playlistItems?part=snippet', token_env,
         {'snippet': {'playlistId': playlist_id, 'resourceId': {'kind': 'youtube#video', 'videoId': video_id}}})


def comment(video_id, text, token_env='YT_REFRESH_TOKEN'):
    """Kanal adına videoya yorum yazar (yalnızca herkese açık videolara yazılabilir)."""
    d = _api('POST', 'https://www.googleapis.com/youtube/v3/commentThreads?part=snippet', token_env,
             {'snippet': {'videoId': video_id, 'topLevelComment': {'snippet': {'textOriginal': text}}}})
    return d.get('id')


def analytics(ids, start, end, token_env='YT_REFRESH_TOKEN'):
    """Video başına izlenme yüzdesi, ortalama izlenme süresi ve kazanılan abone (YouTube Analytics API)."""
    if not ids:
        return {}
    q = urllib.parse.urlencode({'ids': 'channel==MINE', 'startDate': start, 'endDate': end, 'dimensions': 'video',
                                'metrics': 'views,averageViewDuration,averageViewPercentage,subscribersGained,likes,shares',
                                'filters': 'video==' + ','.join(ids[:200]), 'maxResults': 200, 'sort': '-views'})
    d = _api('GET', 'https://youtubeanalytics.googleapis.com/v2/reports?' + q, token_env)
    cols = [c['name'] for c in d.get('columnHeaders', [])]
    return {row[0]: dict(zip(cols[1:], row[1:])) for row in d.get('rows', [])}
