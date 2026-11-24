"""Model indirmeden derinlik haritası (ücretsiz, OpenCV): perspektif + gökyüzü + özne ayrımı (GrabCut).
Çıktı 0 (uzak) .. 1 (yakın). Parallax bu haritayla piksel bazında yapılır: yakın nesneler kamerayla daha çok kayar,
yaklaşırken daha çok büyür; özne (Fatih, karakter, top) arka plandan bağımsız hareket eder."""
import cv2
import numpy as np


def ozne_maskesi(img, kutu, it=4):
    """kutu: [x0, y0, x1, y1] (0..1). GrabCut ile özneyi zeminden ayırır; yumuşak kenarlı maske döner."""
    h, w = img.shape[:2]
    k = 480 / max(h, w)
    kucuk = cv2.resize(img[..., :3], (int(w * k), int(h * k)), interpolation=cv2.INTER_AREA)
    kh, kw = kucuk.shape[:2]
    r = (int(kutu[0] * kw), int(kutu[1] * kh), int((kutu[2] - kutu[0]) * kw), int((kutu[3] - kutu[1]) * kh))
    m = np.zeros((kh, kw), np.uint8)
    bg, fg = np.zeros((1, 65), np.float64), np.zeros((1, 65), np.float64)
    cv2.grabCut(kucuk, m, r, bg, fg, it, cv2.GC_INIT_WITH_RECT)
    on = np.where((m == cv2.GC_FGD) | (m == cv2.GC_PR_FGD), 1.0, 0.0).astype(np.float32)
    # en büyük parçayı tut, delikleri kapat
    n, lab, st, _ = cv2.connectedComponentsWithStats((on > 0).astype(np.uint8))
    if n > 1:
        en = 1 + int(np.argmax(st[1:, cv2.CC_STAT_AREA]))
        on = (lab == en).astype(np.float32)
    on = cv2.morphologyEx(on, cv2.MORPH_CLOSE, np.ones((7, 7), np.uint8))
    on = cv2.GaussianBlur(on, (0, 0), 2.5)
    return cv2.resize(on, (w, h), interpolation=cv2.INTER_LINEAR)


def harita(img, ozne=None, ufuk=0.38):
    """ozne: [x0,y0,x1,y1] verilirse özne en yakın katman olur. ufuk: ufuk çizgisinin yaklaşık yüksekliği (0..1)."""
    h, w = img.shape[:2]
    y = np.linspace(0, 1, h, dtype=np.float32)[:, None]
    # zemin: ufuktan aşağı doğru yakınlaşır; ufkun üstü (dağ/gök) uzak
    zemin = np.clip((y - ufuk) / (1 - ufuk), 0, 1) ** 0.8
    d = np.repeat(0.08 + 0.62 * zemin, w, axis=1)
    # gökyüzü: üst bölgede parlak + düşük doygunluk -> en uzak
    hsv = cv2.cvtColor(cv2.resize(img[..., :3], (w // 4, h // 4)), cv2.COLOR_BGR2HSV).astype(np.float32)
    gok = ((hsv[..., 2] > 150) & (hsv[..., 1] < 90)).astype(np.float32)
    gok = cv2.resize(gok, (w, h)) * (y < ufuk + 0.1)
    d = d * (1 - 0.9 * gok)
    if ozne:
        m = ozne_maskesi(img, ozne)
        d = d * (1 - m) + np.maximum(d, 0.95) * m
        return cv2.GaussianBlur(d, (0, 0), 3).astype(np.float32), m
    return cv2.GaussianBlur(d, (0, 0), 6).astype(np.float32), None
