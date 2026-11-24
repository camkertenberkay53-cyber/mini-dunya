import os

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
FONT = os.path.join(ROOT, 'assets', 'fonts', 'Baloo2.ttf')
EVREN = os.path.join(ROOT, 'evren')
STATE = os.path.join(ROOT, 'state')
EPISODES = os.path.join(ROOT, 'episodes')
OUTPUT = os.path.join(ROOT, 'output')
CONFIG = os.path.join(ROOT, 'config.yaml')


def ucretsiz_mod():
    """config.yaml'da ucretsiz_mod: true ise ücretli anahtar (GEMINI_IMAGE_KEY) hiçbir yerde kullanılmaz."""
    try:
        import yaml
        with open(os.path.join(ROOT, 'config.yaml'), encoding='utf-8') as f:
            return bool((yaml.safe_load(f) or {}).get('ucretsiz_mod'))
    except Exception:
        return True


def ucretli_anahtar():
    """Ücretli anahtar; ücretsiz modda daima boş döner (yanlışlıkla ücretli çağrı yapılamaz)."""
    return '' if ucretsiz_mod() else os.environ.get('GEMINI_IMAGE_KEY', '')
