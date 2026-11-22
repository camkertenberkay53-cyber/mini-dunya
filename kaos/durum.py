"""Teşhis: her iki kanalın adı ve son videolarının YouTube'daki durumu."""
import json
import os
import urllib.request

from . import paths, youtube


def _get(url, tok):
    req = urllib.request.Request(url, headers={'Authorization': f'Bearer {tok}'})
    with urllib.request.urlopen(req, timeout=30) as r:
        return json.loads(r.read())


def main():
    with open(os.path.join(paths.ROOT, 'state', 'hafiza.json'), encoding='utf-8') as f:
        st = json.load(f)
    for env, key in (('YT_REFRESH_TOKEN', 'bolumler'), ('YT_REFRESH_TOKEN_EN', 'en_bolumler')):
        if not youtube.configured(env):
            print(env, 'yok')
            continue
        tok = youtube.access_token(env)
        ch = _get('https://www.googleapis.com/youtube/v3/channels?part=snippet,statistics,status&mine=true', tok)
        for c in ch.get('items', []):
            print(f"\n=== {env}: kanal '{c['snippet']['title']}' id={c['id']} abone={c['statistics'].get('subscriberCount')} "
                  f"video={c['statistics'].get('videoCount')} izlenme={c['statistics'].get('viewCount')} "
                  f"madeForKids={c.get('status', {}).get('madeForKids')} longUploads={c.get('status', {}).get('longUploadsStatus')}")
        ids = [b['video_id'] for b in st.get(key, [])[-8:] if b.get('video_id')]
        if ids:
            d = _get('https://www.googleapis.com/youtube/v3/videos?part=snippet,status,statistics,contentDetails&id=' + ','.join(ids), tok)
            for v in d.get('items', []):
                s = v['status']
                print(f"  {v['id']} | {v['snippet']['title'][:45]} | {s.get('privacyStatus')} publishAt={s.get('publishAt')} "
                      f"upload={s.get('uploadStatus')} red={s.get('rejectionReason')} kids={s.get('madeForKids')} "
                      f"dil={v['snippet'].get('defaultAudioLanguage')} izlenme={v['statistics'].get('viewCount')} "
                      f"yayın={v['snippet'].get('publishedAt')} bölge={v['contentDetails'].get('regionRestriction')}")
            missing = set(ids) - {v['id'] for v in d.get('items', [])}
            if missing:
                print('  BU KANALDA BULUNAMAYANLAR:', missing)


if __name__ == '__main__':
    main()
